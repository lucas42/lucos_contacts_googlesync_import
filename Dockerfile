FROM python:3

WORKDIR /usr/src/app

RUN apt-get update && apt-get install -y pipenv cron

RUN echo "*/5 * * * * root cd `pwd` && pipenv run python -u import.py >> /var/log/cron.log 2>&1" > /etc/cron.d/contacts_import
COPY cron.sh .

COPY Pipfile* ./
RUN pipenv install
COPY *.py ./

CMD [ "./cron.sh"]