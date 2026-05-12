from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trainer', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='trainerdocument',
            name='document_url',
            field=models.URLField(blank=True, default='', max_length=1000),
        ),
    ]
