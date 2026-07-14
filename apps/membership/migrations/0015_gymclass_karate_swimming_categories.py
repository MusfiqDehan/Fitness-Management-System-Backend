from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("membership", "0014_member_relationship_with_member_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="gymclass",
            name="class_type",
            field=models.CharField(
                choices=[
                    ("yoga", "Yoga"),
                    ("hiit", "HIIT"),
                    ("strength", "Strength"),
                    ("cardio", "Cardio"),
                    ("pilates", "Pilates"),
                    ("zumba", "Zumba"),
                    ("karate", "Karate"),
                    ("swimming", "Swimming"),
                    ("other", "Other"),
                ],
                default="other",
                max_length=20,
            ),
        ),
    ]
