from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from apps.membership.models import GymClass
from apps.membership.services.class_schedule_sync import ClassScheduleSyncService
from apps.tenancy.models import Tenant
from apps.trainer.models import TrainerProfile


class Command(BaseCommand):
    help = 'Link existing gym classes to trainer profiles by instructor name and sync trainer classes.'

    def add_arguments(self, parser):
        parser.add_argument('--schema', dest='schema', default=None, help='Limit to one tenant schema')

    def handle(self, *args, **options):
        schema = options.get('schema')
        tenants = Tenant.objects.exclude(schema_name='public')
        if schema:
            tenants = tenants.filter(schema_name=schema)

        total_linked = 0
        total_unmatched = 0

        for tenant in tenants:
            with schema_context(tenant.schema_name):
                unmatched = []
                for gym_class in GymClass.objects.filter(is_deleted=False, trainer_profile__isnull=True):
                    instructor = (gym_class.instructor or '').strip()
                    trainer_profile = None
                    if instructor:
                        trainer_profile = (
                            TrainerProfile.objects.filter(
                                user__full_name__iexact=instructor,
                                is_deleted=False,
                            )
                            .select_related('user')
                            .first()
                        )
                    if trainer_profile is None:
                        unmatched.append({'id': gym_class.id, 'name': gym_class.name, 'instructor': instructor})
                        total_unmatched += 1
                        continue

                    gym_class.trainer_profile = trainer_profile
                    gym_class.save(update_fields=['trainer_profile', 'updated_at'])
                    ClassScheduleSyncService.sync_gym_class_to_trainer_class(gym_class)
                    total_linked += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f'{tenant.schema_name}: linked={total_linked}, unmatched={len(unmatched)}'
                    )
                )
                for row in unmatched:
                    self.stdout.write(f"  unmatched gym_class={row['id']} name={row['name']} instructor={row['instructor']}")

        self.stdout.write(self.style.SUCCESS(f'Done. linked={total_linked}, unmatched={total_unmatched}'))
