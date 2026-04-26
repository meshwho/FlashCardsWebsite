from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("study", "0006_pushreminderlog"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX IF NOT EXISTS auth_user_email_lower_unique
                ON auth_user (LOWER(email))
                WHERE email IS NOT NULL AND email <> '';
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS auth_user_email_lower_unique;
            """,
        ),
    ]