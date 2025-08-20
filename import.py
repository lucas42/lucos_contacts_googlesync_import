import os, traceback
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from schedule_tracker import updateScheduleTracker
from itertools import islice
import requests

try:
	creds = service_account.Credentials.from_service_account_info(
			{
				"private_key": os.environ.get('PRIVATE_KEY'),
				"client_email": os.environ.get('CLIENT_EMAIL'),
				"token_uri": "https://oauth2.googleapis.com/token",
			}, scopes=['https://www.googleapis.com/auth/contacts'], subject=os.environ.get('USER_EMAIL'))

	LUCOS_CONTACTS = os.environ.get('LUCOS_CONTACTS')
	if not LUCOS_CONTACTS:
		exit("LUCOS_CONTACTS environment variable not set - needs to be the URL of a running lucos_contacts instance.")

	EXTERNAL_ID_TYPE='lucos_contacts' # Used for storing & retreiving lucos contact ids in Google's API as an external ID

	headers={
		'Authorization':"key "+os.environ.get('LUCOS_CONTACTS_API_KEY'),
		'User-Agent': "lucos_contacts_googlesync_import",
	}

	service = build('people', 'v1', credentials=creds)

	syncGroup = service.contactGroups().get(
		resourceName=os.environ.get('GROUP'),
		maxMembers=1000,
	).execute()
	remainingResourceNames = syncGroup['memberResourceNames']
	googleContactsToUpdate = {}
	while len(remainingResourceNames) > 0:

		## Google's People API only supports 200 people at once, so split the group into chunks of 200
		next200 = remainingResourceNames[:200]
		remainingResourceNames = remainingResourceNames[200:]
		people = service.people().getBatchGet(
			resourceNames=next200,
			personFields="names,emailAddresses,birthdays,phoneNumbers,photos,externalIds,metadata,memberships"
		).execute()
		for (resourceName, data) in zip(next200, people['responses']):
			person = data['person']

			birthday = {
				'day': None,
				'month': None,
				'year': None,
			}
			for birthday_instance in person.get('birthdays',[]):
				if 'day' in birthday_instance['date']:
					birthday['day'] = birthday_instance['date']['day']
				if 'month' in birthday_instance['date']:
					birthday['month'] = birthday_instance['date']['month']
				if 'year' in birthday_instance['date']:
					birthday['year'] = birthday['date']['year']

			photos = {'CONTACT': None, 'PROFILE': None}
			for photo in person.get('photos',[]):
				if 'default' not in photo:
					photos[photo['metadata']['source']['type']] = photo['url']
			# Prefer photo I've set, but default to their profile pic otherwise
			photoUrl = photos['CONTACT'] or photos['PROFILE']



			## Add items to the accounts list in the order of precedence to find matches
			accounts = []
			accounts.append({
				"type": "googlecontact",

				# Remove the /people/ prefix because Google inconsistently uses different prefixes in different places
				# eg /people/ in its API, but /person/ in its UI
				"contactid": resourceName.replace("people/",""),
			});
			for num in person.get('phoneNumbers',[]):
				accounts.append({
					"type": "phone",
					"number": num['canonicalForm'],
				})
			for email in person.get('emailAddresses',[]):
				accounts.append({
					"type": "email",
					"address": email['value'],
				})
			googlePrimaryName = 'Unknown'
			for name in person.get('names', []):
				accounts.append({
					"type": "name",
					"name": name['displayName'],
				})
				if name['metadata'].get('primary', False):
					googlePrimaryName = name['displayName']

			data = {"identifiers":accounts, "date_of_birth": birthday}

			resp = requests.post(LUCOS_CONTACTS+'agents/import', headers=headers, allow_redirects=False, json=data)
			resp.raise_for_status()
			googleNeedsUpdate = False
			lucosContact = resp.json()["agent"]

			if (lucosContact["name"] != googlePrimaryName):
				print("Mismatch of primary name between "+lucosContact["name"]+" and "+googlePrimaryName+".  Updating google contacts to match lucOS.")
				person['names'] = [{
					'unstructuredName': lucosContact["name"],
					'metadata': { 'primary': True },
				}]
				googleNeedsUpdate = True
			deadGroupMembership = None
			for key, m in enumerate(person.get("memberships", [])):
				if m.get("contactGroupMembership", {}).get("contactGroupResourceName") == os.environ.get('DEAD_GROUP'):
					deadGroupMembership = key
			if lucosContact.get("isDead", False) and deadGroupMembership is None:
				print("Contact "+lucosContact["name"]+" is marked as dead.  Adding label in google.")
				person['memberships'].append({
					"contactGroupMembership": {
						"contactGroupResourceName": os.environ.get('DEAD_GROUP'),
					}
				})
				googleNeedsUpdate = True
			if not lucosContact.get("isDead", False) and deadGroupMembership is not None:
				print("Contact "+lucosContact["name"]+" is marked as not dead.  Removing label in google.")
				del person['memberships'][deadGroupMembership]
				googleNeedsUpdate = True
			favouriteMembership = None
			for key, m in enumerate(person.get("memberships", [])):
				if m.get("contactGroupMembership", {}).get("contactGroupResourceName") == 'contactGroups/starred':
					favouriteMembership = key
			if lucosContact.get("starred", False) and favouriteMembership is None:
				print("Contact "+lucosContact["name"]+" is marked as starred.  Adding to favourites in google.")
				person['memberships'].append({
					"contactGroupMembership": {
						"contactGroupResourceName": os.environ.get('DEAD_GROUP'),
					}
				})
				googleNeedsUpdate = True
			if not lucosContact.get("starred", False) and favouriteMembership is not None:
				print("Contact "+lucosContact["name"]+" is marked as not starred.  Removing from favourites in google.")
				del person['memberships'][favouriteMembership]
				googleNeedsUpdate = True

			# Tidy up phone numbers, particularly because my sibilings end up with so many old ones, it's a mess to keep track of on my phone
			# Could do a similar thing for emails, but they don't tend to accumulate to the same level and it can be useful for gmail to have the old ones listed
			for key, phone in reversed(list(enumerate(person.get('phoneNumbers',[])))):
				normalised = phone['canonicalForm'].replace('+44', '0')
				if normalised not in lucosContact['phone']:
					print("Phone number "+normalised+" for contact "+lucosContact["name"]+" not marked as active in lucOS.  Removing from google contacts.")
					del person['phoneNumbers'][key]
					googleNeedsUpdate = True

			existingexternalid = None
			for externalId in person.get('externalIds', []):
				if externalId['type'] == EXTERNAL_ID_TYPE:
					existingexternalid = externalId['value']
			if str(lucosContact['id']) != existingexternalid:
				print("Adding external_id \""+str(lucosContact["id"])+"\" to contact "+lucosContact["name"])
				if not person.get('externalIds', None):
					person['externalIds'] = []
				person['externalIds'].append({
					'type': EXTERNAL_ID_TYPE,
					'value': str(lucosContact["id"])
				})
				googleNeedsUpdate = True

			if googleNeedsUpdate:
				googleContactsToUpdate[resourceName] = person
	while len(googleContactsToUpdate) > 0:
		next200 = dict(islice(googleContactsToUpdate.items(), 200))
		googleContactsToUpdate = dict(islice(googleContactsToUpdate.items(), 200, None))
		print("Updating "+str(len(next200))+" contacts in Google")
		service.people().batchUpdateContacts(body={
			"contacts": next200,
			"updateMask": "names,memberships,phoneNumbers,externalIds",
		}).execute()

	updateScheduleTracker(success=True)

except Exception as err:
	print(err)
	print(traceback.format_exc())
	updateScheduleTracker(success=False, message=str(err))
