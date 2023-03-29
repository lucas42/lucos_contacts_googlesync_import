import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
import requests

creds = service_account.Credentials.from_service_account_info(
		{
			"private_key": os.environ.get('PRIVATE_KEY'),
			"client_email": os.environ.get('CLIENT_EMAIL'),
			"token_uri": "https://oauth2.googleapis.com/token",
		}, scopes=['https://www.googleapis.com/auth/contacts'], subject=os.environ.get('USER_EMAIL'))

LUCOS_CONTACTS = os.environ.get('LUCOS_CONTACTS')
if not LUCOS_CONTACTS:
	exit("LUCOS_CONTACTS environment variable not set - needs to be the URL of a running lucos_contacts instance.")

LUCOS_HEADERS={'AUTHORIZATION':"key "+os.environ.get('LUCOS_CONTACTS_API_KEY')}

EXTERNAL_ID_TYPE='lucos_test' # Used for storing & retreiving lucos contact ids in Google's people API as an external ID

# Search for an existing match in lucos, starting with phone numbers, then email and falling back to names
# TODO: once Google's People API IDs are stored in lucos, use those with highest priority
# (Currently lucos stores the Google's Contact API IDs, but Google didn't make their IDs backwards compatible, because that'd be too useful)
#
# Returns the agentid as a string, if a match is found.  Otherwise returns None
def matchContact(data):
	for number in data['phoneNumbers']:
		resp = requests.get(LUCOS_CONTACTS+"identify", headers=LUCOS_HEADERS, params={'type':'phone','number':number}, allow_redirects=False)
		if resp.status_code == 302:
			return resp.headers['Location'].replace("/agents/","")
		if resp.status_code == 409:
			print("Conflict for "+data['primaryName']+" - "+number)
		if resp.status_code >= 500:
			resp.raise_for_status()
	for address in data['emailAddresses']:
		resp = requests.get(LUCOS_CONTACTS+"identify", headers=LUCOS_HEADERS, params={'type':'email','address':address}, allow_redirects=False)
		if resp.status_code == 302:
			return resp.headers['Location'].replace("/agents/","")
		if resp.status_code == 409:
			print("Conflict for "+data['primaryName']+" - "+address)
		if resp.status_code >= 500:
			resp.raise_for_status()
	resp = requests.get(LUCOS_CONTACTS+"identify", headers=LUCOS_HEADERS, params={'type':'name','name':data['primaryName']}, allow_redirects=False)
	if resp.status_code == 302:
		return resp.headers['Location'].replace("/agents/","")
	if resp.status_code == 409:
		print("Conflict for "+data['primaryName']+" - name")
	if resp.status_code >= 500:
		resp.raise_for_status()
	return None

def newContact(name):
	resp = requests.post(LUCOS_CONTACTS+"agents/add", headers=LUCOS_HEADERS, allow_redirects=False, data={'name': name})
	if resp.status_code == 302:
		return resp.headers['Location'].replace("/agents/","")
	raise Exception("Unexpected status code "+str(resp.status_code)+" "+resp.reason+": "+resp.text)

try:
	service = build('people', 'v1', credentials=creds)

	syncGroup = service.contactGroups().get(
		resourceName=os.environ.get('GROUP'),
		maxMembers=9, #NOCOMMIT
	).execute()
	remainingResourceNames = syncGroup['memberResourceNames']
	while len(remainingResourceNames) > 0:
		contactsToUpdate = {}

		## Google's People API only supports 200 people at once, so split the group into chunks of 200
		next200 = remainingResourceNames[:200]
		remainingResourceNames = remainingResourceNames[200:]
		people = service.people().getBatchGet(
			resourceNames=next200,
			personFields="names,emailAddresses,birthdays,phoneNumbers,photos,externalIds,metadata"
		).execute()
		for (resourceName, data) in zip(next200, people['responses']):
			person = data['person']
			output = {
				'primaryName': 'Unknown Google Contact',
				'phoneNumbers': [],
				'emailAddresses': [],
			}
			for name in person['names']:
				if name['metadata']['primary']:
					output['primaryName'] = name['displayName']
			if 'emailAddresses' in person:
				output['emailAddresses'] = [email['value'] for email in person['emailAddresses']]
			if 'phoneNumbers' in person:
				output['phoneNumbers'] = [num['canonicalForm'] for num in person['phoneNumbers']]
			if 'birthdays' in person:
				day = None
				month = None
				year = None
				for birthday in person['birthdays']:
					if 'day' in birthday['date']:
						day = birthday['date']['day']
					if 'month' in birthday['date']:
						month = birthday['date']['month']
					if 'year' in birthday['date']:
						year = birthday['date']['year']
				output['birthday'] = {
					day: day,
					month: month,
					year: year,
				}
			if 'photos' in person:
				photos = {'CONTACT': None, 'PROFILE': None}
				for photo in person['photos']:
					if 'default' not in photo:
						photos[photo['metadata']['source']['type']] = photo['url']
				# Prefer photo I've set, but default to their profile pic otherwise
				output['photoUrl'] = photos['CONTACT'] or photos['PROFILE']

			print(output)

			existingcontactid = None
			externalIds = person.get('externalIds', [])
			for externalId in externalIds:
				if externalId['type'] == EXTERNAL_ID_TYPE:
					existingcontactid = externalId['value']

			contactid = existingcontactid
			if not contactid:
				print("No existing lucos ID found for contact, trying to match against existing lucos contacts...")
				contactid = matchContact(output)
			if not contactid:
				print("No matching lucos contact found, creating new one...")
				contactid = newContact(output['primaryName'])
			print(contactid or "NOT FOUND")

			if not existingcontactid:
				externalIds.append({'type':EXTERNAL_ID_TYPE, 'value': contactid})
				contactsToUpdate[resourceName] = {'metadata': person['metadata'], 'externalIds': externalIds}
		if contactsToUpdate:
			print("update lucos ids in google", contactsToUpdate)
			service.people().batchUpdateContacts(body={
				"contacts": contactsToUpdate,
				"updateMask": "externalIds",
			}).execute()

except HttpError as err:
	print(err)
