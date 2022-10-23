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
		}, scopes=['https://www.googleapis.com/auth/contacts.readonly'], subject=os.environ.get('USER_EMAIL'))

LUCOS_CONTACTS = os.environ.get('LUCOS_CONTACTS')
if not LUCOS_CONTACTS:
	exit("LUCOS_CONTACTS environment variable not set - needs to be the URL of a running lucos_contacts instance.")

LUCOS_HEADERS={'AUTHORIZATION':"key "+os.environ.get('LUCOS_CONTACTS_API_KEY')}

EXTERNAL_ID_TYPE='lucos' # Used for retreiving lucos contact ids in Google's people API as an external ID

# Search for an existing match in lucos, based on the order of items in the accounts arround
#
# Returns the agentid as a string, if a match is found.  Otherwise returns None
def matchContact(accounts, primaryName):
	for account in accounts:
		resp = requests.get(LUCOS_CONTACTS+"identify", headers=LUCOS_HEADERS, params=account, allow_redirects=False)
		if resp.status_code == 302:
			return resp.headers['Location'].replace("/agents/","")
		if resp.status_code == 409:
			print("Conflict for "+primaryName+" - "+account['type'])
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
				"contactid": resourceName,
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
			primaryName = 'Unknown Google Contact'
			for name in person.get('names', []):
				if name['metadata']['primary']:
					primaryName = name['displayName']
				accounts.append({
					"type": "name",
					"name": name['displayName'],
				})

			print(primaryName, accounts)

			contactid = None
			externalIds = person.get('externalIds', [])
			for externalId in externalIds:
				if externalId['type'] == EXTERNAL_ID_TYPE:
					contactid = externalId['value']
			if not contactid:
				print("No existing lucos ID found for contact, trying to match against existing lucos contacts...")
				contactid = matchContact(accounts, primaryName)
			if not contactid:
				print("No matching lucos contact found, creating new one...")
				contactid = newContact(primaryName)
			print(contactid or "NOT FOUND")



except HttpError as err:
	print(err)
