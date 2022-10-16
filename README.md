# lucos_contacts_googlesync_import
Imports contact info from google on an hourly cron schedule

## Dependencies

* docker
* docker-compose

## Remote Dependencies

* [lucos_contacts](https://github.com/lucas42/lucos_contacts)
* [Google People API](https://developers.google.com/people)

## Build-time Dependencies (Installed by Dockerfile)

* [python 3](https://www.python.org/download/releases/3.0/)

## Running
`nice -19 docker-compose up -d --no-build`

## Running script without cron

To test the script logic with worrying about cronjobs.

Set `entrypoint: pipenv run python -u import.py` in the docker-compose file (or equivalent)

## Running locally

Run `pipenv install` to setup

`pipenv run python import.py`


## Environment Variables
For local development, these should be stored in a .env file

* _**USER_EMAIL**_ The email address of the google account to fetch contacts from
* _**GROUP**_ The resourceName of the contact group in the about account to fetch contacts from (usually in the form `contactGroups/<alphanumeric_code>`)
* _**CLIENT_EMAIL**_ The Email Address for a Google IAM Service Account, which has `https://www.googleapis.com/auth/contacts.readonly` scope delegated to it
* _**PRIVATE_KEY**_ The Corresponding Private Key for the same Service Account

## File structure

* `Dockerfile`, `Pipfile`, `Pipfile.lock` and the `.cirleci` directory are used at build time
* `cron.sh` ensures the cron daemon is running with the right environment set up and sharing its logs in a way that get surfaced to Docker
* `import.py` Imports from Google's People API to lucos_contacts