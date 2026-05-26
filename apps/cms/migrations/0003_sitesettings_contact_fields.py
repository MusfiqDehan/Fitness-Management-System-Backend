from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cms', '0002_alter_promobanner_options_promobanner_alt_text_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='phone',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='email',
            field=models.EmailField(blank=True, default='', max_length=254),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='address',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='website',
            field=models.URLField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='timezone',
            field=models.CharField(blank=True, default='', max_length=50),
        ),
    ]
