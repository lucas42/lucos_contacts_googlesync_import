import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from schedule_tracker import updateScheduleTracker
import requests

try:
	creds = service_account.Credentials.from_service_account_info(
			{
				"private_key": os.environ.get('PRIVATE_KEY'),
				"client_email": os.environ.get('CLIENT_EMAIL'),
				"token_uri": "https://oauth2.googleapis.com/token",
			}, scopes=['https://www.googleapis.com/auth/contacts.readonly'], subject=os.environ.get('USER_EMAIL'))

	LUCOS_CONTACTS = os.environ.get('LUCOS_CONTACTS')
	if not LUCOS_CONTACTS:
		exit("LUCOS_CONTACTS environment variable not set - needs to be the URL of a running lucos_contacts instance.")

	LUCOS_HEADERS={'AUTHORIZATION':"key "+os.environ.get('LUCOS_CONTACTS_API_KEY')}

	service = build('people', 'v1', credentials=creds)

	syncGroup = service.contactGroups().get(
		resourceName=os.environ.get('GROUP'),
		maxMembers=1000,
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
			for name in person.get('names', []):
				accounts.append({
					"type": "name",
					"name": name['displayName'],
				})

			data = {"identifiers":accounts, "date_of_birth": birthday}

			resp = requests.post(LUCOS_CONTACTS+'agents/import', headers=LUCOS_HEADERS, allow_redirects=False, json=data)
			resp.raise_for_status()
	updateScheduleTracker(success=True)

except Exception as err:
	print(err)
	updateScheduleTracker(success=False, message=str(err))
