FROM lucas42/lucos_scheduled_scripts:2.0.2

RUN pip install pipenv
RUN echo "*/5 * * * * pipenv run python -u import.py" | crontab -

COPY Pipfile* ./
RUN pipenv install
COPY *.py ./