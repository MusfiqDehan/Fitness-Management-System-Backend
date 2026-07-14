import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('membership', '0016_member_name_phone_dob_unique'),
    ]

    operations = [
        migrations.CreateModel(
            name='ClassEnrollment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True, help_text='Whether this item is active and usable')),
                ('is_published', models.BooleanField(default=False, help_text='Whether this item is published/visible')),
                ('is_deleted', models.BooleanField(default=False)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('enrolled_at', models.DateTimeField(auto_now_add=True)),
                ('status', models.CharField(choices=[('active', 'Active'), ('removed', 'Removed')], default='active', max_length=20)),
                ('source', models.CharField(choices=[('admin', 'Admin'), ('self', 'Self')], default='admin', max_length=20)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_created_records', to=settings.AUTH_USER_MODEL)),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_deleted_records', to=settings.AUTH_USER_MODEL)),
                ('enrolled_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='class_enrollments_created', to=settings.AUTH_USER_MODEL)),
                ('gym_class', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='enrollments', to='membership.gymclass')),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='class_enrollments', to='membership.member')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_updated_records', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-enrolled_at'],
            },
        ),
        migrations.AddIndex(
            model_name='classenrollment',
            index=models.Index(condition=models.Q(('is_deleted', False)), fields=['gym_class', 'status'], name='idx_classenroll_class_status'),
        ),
        migrations.AddIndex(
            model_name='classenrollment',
            index=models.Index(condition=models.Q(('is_deleted', False)), fields=['member', 'status'], name='idx_classenroll_member_status'),
        ),
        migrations.AddConstraint(
            model_name='classenrollment',
            constraint=models.UniqueConstraint(condition=models.Q(('is_deleted', False)), fields=('gym_class', 'member'), name='uniq_active_class_enrollment'),
        ),
    ]
