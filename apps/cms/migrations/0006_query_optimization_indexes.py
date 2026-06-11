from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0005_alter_pagecontent_page_name"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="blog",
            index=models.Index(
                fields=["status", "published_date"],
                name="idx_cmsblog_status_pubdate",
            ),
        ),
        migrations.AddIndex(
            model_name="blog",
            index=models.Index(
                fields=["status", "is_show_on_home_page"],
                name="idx_cmsblog_status_home",
            ),
        ),
    ]
