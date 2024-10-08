FROM python:3.13-alpine

WORKDIR /usr/src/app

RUN pip install pipenv
# Default version of sed in alpine isn't the full GNU one, so install that
RUN apk add sed

RUN echo "*/5 * * * * cd `pwd` && pipenv run python -u import.py >> /var/log/cron.log 2>&1" | crontab -
COPY cron.sh .

COPY Pipfile* ./
RUN pipenv install
COPY *.py ./

CMD [ "./cron.sh"]