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

# Search for an existing match in lucos, starting with phone numbers, then email and falling back to names
# TODO: once Google's People API IDs are stored in lucos, use those with highest priority
# (Currently lucos stores the Google's Contact API IDs, but Google didn't make their IDs backwards compatible, because that'd be too useful)
def matchContact(data):
	for number in data['phoneNumbers']:
		resp = requests.get(LUCOS_CONTACTS+"identify", params={'type':'phone','number':number}, allow_redirects=False)
		if resp.status_code == 302:
			return resp.headers['Location']
		if resp.status_code == 406:
			print("Conflict for "+data['primaryName']+" - "+number)
	for address in data['emailAddresses']:
		resp = requests.get(LUCOS_CONTACTS+"identify", params={'type':'email','address':address}, allow_redirects=False)
		if resp.status_code == 302:
			return resp.headers['Location']
		if resp.status_code == 406:
			print("Conflict for "+data['primaryName']+" - "+address)
	resp = requests.get(LUCOS_CONTACTS+"identify", params={'type':'name','name':data['primaryName']}, allow_redirects=False)
	if resp.status_code == 302:
		return resp.headers['Location']
	if resp.status_code == 406:
		print("Conflict for "+data['primaryName']+" - name")
	return None


try:
	service = build('people', 'v1', credentials=creds)

	syncGroup = service.contactGroups().get(
		resourceName=os.environ.get('GROUP'),
		maxMembers=1000,
	).execute()
	remainingResourceNames = syncGroup['memberResourceNames']
	while len(remainingResourceNames) > 0:

		## Google's People API only supports 200 people at once, so split the group into chunks of 200
		next200 = remainingResourceNames[:200]
		remainingResourceNames = remainingResourceNames[200:]
		people = service.people().getBatchGet(
			resourceNames=next200,
			personFields="names,emailAddresses,birthdays,phoneNumbers,photos"
		).execute()
		for data in people['responses']:
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
			contact_path = matchContact(output)
			print(contact_path or "NOT FOUND")

except HttpError as err:
	print(err)
