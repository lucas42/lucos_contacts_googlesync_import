FROM lucas42/lucos_scheduled_scripts

RUN pip install pipenv
RUN echo "* * * * * pipenv run python -u import.py" | crontab -

COPY Pipfile* ./
RUN pipenv install
COPY *.py ./