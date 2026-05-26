from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='gymprofile',
            name='logo_url',
            field=models.URLField(blank=True, default='', max_length=1000),
        ),
        migrations.AddField(
            model_name='gymprofile',
            name='logo_width',
            field=models.PositiveIntegerField(default=120),
        ),
        migrations.AddField(
            model_name='gymprofile',
            name='logo_height',
            field=models.PositiveIntegerField(default=40),
        ),
    ]
