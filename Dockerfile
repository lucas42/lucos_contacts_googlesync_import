FROM lucas42/lucos_scheduled_scripts:1.0.0

RUN pip install pipenv
RUN echo "*/5 * * * * pipenv run python -u import.py" | crontab -

COPY Pipfile* ./
RUN pipenv install
COPY *.py ./