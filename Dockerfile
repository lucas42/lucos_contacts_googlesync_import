FROM lucas42/lucos_scheduled_scripts

RUN pip install pipenv
RUN echo "*/5 * * * * pipenv run python -u import.py" | crontab -

COPY Pipfile* ./
RUN pipenv install
COPY *.py ./