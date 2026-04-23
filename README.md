# FlashCardsWebsite

Django-based flashcards platform with spaced repetition (FSRS), deck practice modes, review schedule, sentence practice, audit log, PostgreSQL, Gunicorn, Nginx, and Docker.

## Stack

- Python 3.12
- Django 5.2
- PostgreSQL 16
- Gunicorn
- Nginx
- Docker / Docker Compose

## Requirements

- Docker
- Docker Compose plugin

## Environment variables

Create a `.env` file in the project root.

Example:

```env
DJANGO_SECRET_KEY=change-me-to-a-long-random-secret
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
DJANGO_TIME_ZONE=Europe/Kyiv

POSTGRES_DB=flashcards
POSTGRES_USER=flashcards_user
POSTGRES_PASSWORD=change-me
POSTGRES_HOST=db
POSTGRES_PORT=5432