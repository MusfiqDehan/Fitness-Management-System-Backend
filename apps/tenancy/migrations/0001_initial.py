from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='Tenant',
            fields=[
                ('schema_name', models.CharField(
                    db_index=True,
                    max_length=63,
                    unique=True,
                    verbose_name='Schema Name',
                )),
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('slug', models.SlugField(unique=True)),
                ('code', models.CharField(max_length=50, unique=True)),
                ('timezone', models.CharField(default='UTC', max_length=50)),
                ('currency', models.CharField(default='USD', max_length=10)),
                ('locale', models.CharField(default='en', max_length=10)),
                ('plan', models.CharField(default='free', max_length=50)),
                ('billing_email', models.EmailField(blank=True, max_length=254)),
                ('subscription_start', models.DateTimeField(blank=True, null=True)),
                ('subscription_end', models.DateTimeField(blank=True, null=True)),
                ('is_trial', models.BooleanField(default=True)),
                ('trial_ends_at', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(
                    choices=[
                        ('active', 'Active'),
                        ('suspended', 'Suspended'),
                        ('cancelled', 'Cancelled'),
                        ('trial', 'Trial'),
                    ],
                    default='trial',
                    max_length=20,
                )),
                ('max_users', models.IntegerField(default=10)),
                ('max_branches', models.IntegerField(default=1)),
                ('features', models.JSONField(blank=True, default=dict)),
                ('owner_email', models.EmailField(blank=True, null=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['name'],
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Domain',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('domain', models.CharField(db_index=True, max_length=253, unique=True)),
                ('is_primary', models.BooleanField(db_index=True, default=True)),
                ('tenant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='domains',
                    to='tenancy.tenant',
                )),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
