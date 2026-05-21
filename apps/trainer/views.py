from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Avg, Sum
from django.utils import timezone

from utils.base_view import ModelCRUDView
from apps.access.permissions import HasFeatureMethodPermission
from apps.access.utils import user_can
from .models import (
    TrainerProfile, TrainerDocument, TrainerClass,
    TrainerSchedule, ScheduleBooking, TrainerRating, TrainerInvitation,
)
from .serializers import (
    TrainerProfileSerializer, TrainerDocumentSerializer,
    TrainerDocumentPublicSerializer,
    TrainerClassSerializer, TrainerScheduleSerializer,
    ScheduleBookingSerializer, ScheduleBookingCreateSerializer,
    TrainerRatingSerializer, TrainerRatingCreateSerializer,
    TrainerInvitationSerializer, TrainerInvitationCreateSerializer,
    TrainerProfilePublicSerializer, TrainerProfileMinimalSerializer,
    TrainerClassPublicSerializer, TrainerSchedulePublicSerializer,
    VerifyTrainerInvitationSerializer, CompleteTrainerRegistrationSerializer,
)


def _is_trainer_user(user) -> bool:
    return bool(getattr(user, 'is_authenticated', False) and getattr(user, 'role', '') == 'trainer')


def _get_trainer_profile_for_user(user):
    return TrainerProfile.objects.filter(user=user, is_deleted=False).first()


class IsTrainerOrFeaturePermission(BasePermission):
    """Allow trainer-role users; otherwise enforce tenant feature permission checks."""

    safe_methods = {'GET', 'HEAD', 'OPTIONS'}

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False

        if _is_trainer_user(user):
            return True

        feature_keys = list(getattr(view, 'feature_keys', []) or [])
        feature_key = getattr(view, 'feature_key', '')
        if feature_key:
            feature_keys.append(feature_key)
        if not feature_keys:
            return False

        method_permission_map = getattr(view, 'method_permission_map', {}) or {}
        required_level = method_permission_map.get(request.method)
        if required_level is None:
            required_level = getattr(
                view,
                'read_level' if request.method in self.safe_methods else 'write_level',
                'view' if request.method in self.safe_methods else 'edit',
            )

        return any(user_can(user, key, required_level) for key in feature_keys)


# =============================================================================
# ACTIONS MIXIN
# =============================================================================
class TrainerModelActions:
    """Shared action handlers for trainer-related views."""
    
    def _recalc(self, request, pk, field=None):
        try:
            obj = self.queryset.model.objects.get(pk=pk)
        except self.queryset.model.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        
        if hasattr(obj, 'recalc_stats'):
            obj.recalc_stats()
        return Response({'message': 'Stats recalculated'})

    actions = {
        'recalc': lambda self, req, pk: self._recalc(req, pk),
    }


# =============================================================================
# TRAINER PROFILE
# =============================================================================
class TrainerProfileView(TrainerModelActions, ModelCRUDView):
    """CRUD for TrainerProfile + actions."""
    feature_key = 'instructors'
    feature_keys = ['trainer']
    queryset = TrainerProfile.objects.select_related('user').all()
    serializer_class = TrainerProfileSerializer
    permission_classes = [IsTrainerOrFeaturePermission]

    actions = {
        'recalc': lambda self, req, pk: self._recalc(req, pk),
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if _is_trainer_user(self.request.user):
            queryset = queryset.filter(user=self.request.user)
        return queryset

    def _create(self, request):
        if _is_trainer_user(request.user):
            return Response({'error': 'Trainer profiles are created through invitation flow only.'}, status=status.HTTP_403_FORBIDDEN)
        return super()._create(request)

    def _list(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        # Highlighted trainers first
        queryset = queryset.order_by('-is_highlighted', '-average_rating', 'user__full_name')
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class TrainerProfileMeView(APIView):
    """GET /api/v1/trainer/me/ — current trainer's profile."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = TrainerProfile.objects.get(user=request.user, is_deleted=False)
        except TrainerProfile.DoesNotExist:
            return Response({'error': 'Trainer profile not found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = TrainerProfileSerializer(profile)
        return Response(serializer.data)


class TrainerProfileHighlightToggleView(APIView):
    """PATCH /api/v1/trainer/{pk}/highlight/ — toggle highlighted status."""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            profile = TrainerProfile.objects.get(pk=pk, is_deleted=False)
        except TrainerProfile.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        profile.is_highlighted = not profile.is_highlighted
        profile.save(update_fields=['is_highlighted'])
        return Response({'is_highlighted': profile.is_highlighted})


class TopTrainersView(APIView):
    """GET /api/v1/trainer/top/ — top highlighted trainers for landing page."""
    permission_classes = [AllowAny]

    def get(self, request):
        trainers = TrainerProfile.objects.filter(
            is_highlighted=True,
            is_published=True,
            is_deleted=False,
            user__is_active=True,
        ).select_related('user').order_by('-average_rating', '-total_ratings')[:10]
        serializer = TrainerProfilePublicSerializer(trainers, many=True, context={'request': request})
        return Response(serializer.data)


class TrainerPublicProfileView(APIView):
    """GET /api/v1/trainer/public/{username}/ — public profile page."""
    permission_classes = [AllowAny]

    def get(self, request, username):
        try:
            profile = TrainerProfile.objects.get(
                username=username,
                is_published=True,
                is_deleted=False,
                user__is_active=True,
            )
        except TrainerProfile.DoesNotExist:
            return Response({'error': 'Trainer not found'}, status=status.HTTP_404_NOT_FOUND)
        
        ctx = {'request': request}
        serializer = TrainerProfilePublicSerializer(profile, context=ctx)
        data = serializer.data

        # Keep public rating summary in sync even if denormalized fields are stale.
        ratings_qs = TrainerRating.objects.filter(trainer=profile, is_deleted=False)
        ratings_avg = ratings_qs.aggregate(avg=Avg('rating'))['avg'] or 0
        data['average_rating'] = round(float(ratings_avg), 1)
        data['total_ratings'] = ratings_qs.count()

        # Keep class/member counters in sync even if denormalized fields are stale.
        data['total_classes'] = TrainerClass.objects.filter(
            trainer=profile,
            is_deleted=False,
        ).count()
        data['total_members'] = ScheduleBooking.objects.filter(
            schedule__trainer=profile,
            is_deleted=False,
        ).values('member').distinct().count()
        
        # Include classes
        classes = TrainerClass.objects.filter(
            trainer=profile, is_published=True, is_deleted=False
        ).order_by('name')
        data['classes'] = TrainerClassPublicSerializer(classes, many=True, context=ctx).data
        
        # Include ratings
        ratings = ratings_qs.select_related('member').order_by('-created_at')[:20]
        data['recent_ratings'] = TrainerRatingSerializer(ratings, many=True, context=ctx).data

        # Include published public documents (certifications, awards, body images, etc.)
        documents = TrainerDocument.objects.filter(
            trainer=profile,
            is_published=True,
            is_deleted=False,
        ).order_by('-issue_date', '-created_at')
        data['documents'] = TrainerDocumentPublicSerializer(documents, many=True, context=ctx).data
        
        return Response(data)


# =============================================================================
# TRAINER DOCUMENT
# =============================================================================
class TrainerDocumentView(TrainerModelActions, ModelCRUDView):
    """CRUD for TrainerDocument."""
    feature_key = 'instructors'
    feature_keys = ['trainer']
    queryset = TrainerDocument.objects.select_related('trainer__user').all()
    serializer_class = TrainerDocumentSerializer
    permission_classes = [IsTrainerOrFeaturePermission]

    actions = {
        'recalc': lambda self, req, pk: self._recalc(req, pk),
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if _is_trainer_user(self.request.user):
            queryset = queryset.filter(trainer__user=self.request.user)
        return queryset

    def _create(self, request):
        if _is_trainer_user(request.user):
            profile = _get_trainer_profile_for_user(request.user)
            if profile is None:
                return Response({'error': 'Trainer profile not found'}, status=status.HTTP_404_NOT_FOUND)
            data = request.data.copy()
            data['trainer'] = profile.id
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            instance = serializer.save()
            return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)
        return super()._create(request)

    def _list(self, request):
        # Filter by trainer from query param
        trainer_id = request.query_params.get('trainer')
        queryset = self.filter_queryset(self.get_queryset())
        if trainer_id:
            queryset = queryset.filter(trainer_id=trainer_id)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


# =============================================================================
# TRAINER CLASS
# =============================================================================
class TrainerClassView(TrainerModelActions, ModelCRUDView):
    """CRUD for TrainerClass."""
    feature_key = 'instructors'
    feature_keys = ['trainer']
    queryset = TrainerClass.objects.select_related('trainer__user').all()
    serializer_class = TrainerClassSerializer
    permission_classes = [IsTrainerOrFeaturePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        if _is_trainer_user(self.request.user):
            queryset = queryset.filter(trainer__user=self.request.user)
        return queryset

    def _create(self, request):
        if _is_trainer_user(request.user):
            profile = _get_trainer_profile_for_user(request.user)
            if profile is None:
                return Response({'error': 'Trainer profile not found'}, status=status.HTTP_404_NOT_FOUND)
            data = request.data.copy()
            data['trainer'] = profile.id
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            instance = serializer.save()
            if getattr(instance, 'trainer', None) and hasattr(instance.trainer, 'recalc_stats'):
                instance.trainer.recalc_stats()
            return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        if getattr(instance, 'trainer', None) and hasattr(instance.trainer, 'recalc_stats'):
            instance.trainer.recalc_stats()
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    def _update(self, pk, request, partial):
        instance = self.get_object()
        old_trainer = getattr(instance, 'trainer', None)
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        # Recalculate old/new trainer stats in case trainer ownership changed.
        if old_trainer and hasattr(old_trainer, 'recalc_stats'):
            old_trainer.recalc_stats()
        if getattr(updated, 'trainer', None) and hasattr(updated.trainer, 'recalc_stats'):
            updated.trainer.recalc_stats()

        return Response(self.get_serializer(updated).data)

    def _destroy(self, pk):
        instance = self.get_object()
        trainer = getattr(instance, 'trainer', None)
        instance.delete()
        if trainer and hasattr(trainer, 'recalc_stats'):
            trainer.recalc_stats()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _list(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        trainer_id = request.query_params.get('trainer')
        if trainer_id:
            queryset = queryset.filter(trainer_id=trainer_id)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class TrainerClassListPublicView(APIView):
    """GET /api/v1/trainer/class/public/ — public class listing."""
    permission_classes = [AllowAny]

    def get(self, request):
        queryset = TrainerClass.objects.filter(
            is_published=True,
            is_deleted=False,
        ).select_related('trainer__user')
        
        category = request.query_params.get('category')
        trainer_id = request.query_params.get('trainer')
        difficulty = request.query_params.get('difficulty')
        
        if category:
            queryset = queryset.filter(category__iexact=category)
        if trainer_id:
            queryset = queryset.filter(trainer_id=trainer_id)
        if difficulty:
            queryset = queryset.filter(difficulty_level=difficulty)
        
        queryset = queryset.order_by('name')
        serializer = TrainerClassPublicSerializer(queryset, many=True)
        return Response(serializer.data)


# =============================================================================
# TRAINER SCHEDULE
# =============================================================================
class TrainerScheduleView(TrainerModelActions, ModelCRUDView):
    """CRUD for TrainerSchedule."""
    feature_key = 'instructors'
    feature_keys = ['trainer']
    queryset = TrainerSchedule.objects.select_related(
        'trainer_class', 'trainer__user'
    ).all()
    serializer_class = TrainerScheduleSerializer
    permission_classes = [IsTrainerOrFeaturePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        if _is_trainer_user(self.request.user):
            queryset = queryset.filter(trainer__user=self.request.user)
        return queryset

    def _create(self, request):
        if _is_trainer_user(request.user):
            profile = _get_trainer_profile_for_user(request.user)
            if profile is None:
                return Response({'error': 'Trainer profile not found'}, status=status.HTTP_404_NOT_FOUND)

            trainer_class_id = request.data.get('trainer_class')
            trainer_class = TrainerClass.objects.filter(pk=trainer_class_id, trainer=profile, is_deleted=False).first()
            if trainer_class is None:
                return Response({'error': 'Class not found or not owned by this trainer'}, status=status.HTTP_400_BAD_REQUEST)

            data = request.data.copy()
            data['trainer'] = profile.id
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            instance = serializer.save()
            return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)
        return super()._create(request)

    def _list(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        trainer_id = request.query_params.get('trainer')
        class_id = request.query_params.get('class')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        
        if trainer_id:
            queryset = queryset.filter(trainer_id=trainer_id)
        if class_id:
            queryset = queryset.filter(trainer_class_id=class_id)
        if date_from:
            queryset = queryset.filter(scheduled_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(scheduled_date__lte=date_to)
        
        queryset = queryset.order_by('scheduled_date', 'start_time')
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class TrainerSchedulePublicView(APIView):
    """GET /api/v1/trainer/schedule/public/ — public schedule for booking."""
    permission_classes = [AllowAny]

    def get(self, request):
        queryset = TrainerSchedule.objects.filter(
            is_published=True,
            is_deleted=False,
            is_cancelled=False,
        ).select_related('trainer_class', 'trainer__user').order_by('scheduled_date', 'start_time')
        
        trainer_id = request.query_params.get('trainer')
        class_id = request.query_params.get('class')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        
        if trainer_id:
            queryset = queryset.filter(trainer_id=trainer_id)
        if class_id:
            queryset = queryset.filter(trainer_class_id=class_id)
        if date_from:
            queryset = queryset.filter(scheduled_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(scheduled_date__lte=date_to)
        
        # Only future schedules
        queryset = queryset.filter(scheduled_date__gte=timezone.now().date())
        
        serializer = TrainerSchedulePublicSerializer(queryset, many=True)
        return Response(serializer.data)


# =============================================================================
# SCHEDULE BOOKING
# =============================================================================
class ScheduleBookingView(APIView):
    """POST /api/v1/trainer/booking/ — book a schedule slot."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ScheduleBookingCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        booking = serializer.save()
        trainer = getattr(getattr(booking, 'schedule', None), 'trainer', None)
        if trainer and hasattr(trainer, 'recalc_stats'):
            trainer.recalc_stats()
        return Response(
            ScheduleBookingSerializer(booking).data,
            status=status.HTTP_201_CREATED
        )


class MyBookingsView(APIView):
    """GET /api/v1/trainer/booking/me/ — member's bookings."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            member = request.user.member
        except Exception:
            return Response({'error': 'Member profile not found'}, status=status.HTTP_404_NOT_FOUND)
        
        bookings = ScheduleBooking.objects.filter(
            member=member,
            is_deleted=False,
        ).select_related(
            'schedule__trainer_class', 'schedule__trainer__user'
        ).order_by('-schedule__scheduled_date', '-schedule__start_time')
        
        # Filter by status if provided
        status_filter = request.query_params.get('status')
        if status_filter:
            bookings = bookings.filter(status=status_filter)
        
        serializer = ScheduleBookingSerializer(bookings, many=True)
        return Response(serializer.data)


class BookingCheckInView(APIView):
    """PATCH /api/v1/trainer/booking/{pk}/checkin/ — check in to a booked session."""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            booking = ScheduleBooking.objects.get(pk=pk, is_deleted=False)
        except ScheduleBooking.DoesNotExist:
            return Response({'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
        
        booking.check_in_time = timezone.now()
        booking.status = 'attended'
        booking.save(update_fields=['check_in_time', 'status'])
        trainer = getattr(getattr(booking, 'schedule', None), 'trainer', None)
        if trainer and hasattr(trainer, 'recalc_stats'):
            trainer.recalc_stats()
        return Response(ScheduleBookingSerializer(booking).data)


class BookingCancelView(APIView):
    """PATCH /api/v1/trainer/booking/{pk}/cancel/ — cancel a booking."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        try:
            booking = ScheduleBooking.objects.get(pk=pk, is_deleted=False)
        except ScheduleBooking.DoesNotExist:
            return Response({'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Update schedule participant count
        schedule = booking.schedule
        schedule.current_participants = max(0, schedule.current_participants - 1)
        schedule.save(update_fields=['current_participants'])
        
        booking.status = 'cancelled'
        booking.save(update_fields=['status'])
        trainer = getattr(getattr(booking, 'schedule', None), 'trainer', None)
        if trainer and hasattr(trainer, 'recalc_stats'):
            trainer.recalc_stats()
        return Response({'message': 'Booking cancelled'})


# =============================================================================
# TRAINER RATING
# =============================================================================
class TrainerRatingView(TrainerModelActions, ModelCRUDView):
    """CRUD for TrainerRating."""
    feature_key = 'instructors'
    feature_keys = ['trainer']
    queryset = TrainerRating.objects.select_related('trainer__user', 'member').all()
    serializer_class = TrainerRatingSerializer
    permission_classes = [IsTrainerOrFeaturePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        if _is_trainer_user(self.request.user):
            profile = _get_trainer_profile_for_user(self.request.user)
            if profile is None:
                return queryset.none()
            queryset = queryset.filter(trainer=profile)
        return queryset

    def _create(self, request):
        if _is_trainer_user(request.user):
            raise PermissionDenied('Trainers cannot create ratings.')
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        if getattr(instance, 'trainer', None) and hasattr(instance.trainer, 'recalc_stats'):
            instance.trainer.recalc_stats()
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    def _update(self, pk, request, partial):
        if _is_trainer_user(request.user):
            raise PermissionDenied('Trainers cannot modify ratings.')
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        if getattr(updated, 'trainer', None) and hasattr(updated.trainer, 'recalc_stats'):
            updated.trainer.recalc_stats()
        return Response(self.get_serializer(updated).data)

    def _destroy(self, pk):
        if _is_trainer_user(self.request.user):
            raise PermissionDenied('Trainers cannot delete ratings.')
        instance = self.get_object()
        trainer = getattr(instance, 'trainer', None)
        instance.delete()
        if trainer and hasattr(trainer, 'recalc_stats'):
            trainer.recalc_stats()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _list(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        trainer_id = request.query_params.get('trainer')
        if trainer_id:
            queryset = queryset.filter(trainer_id=trainer_id)
        queryset = queryset.order_by('-created_at')
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class RateTrainerView(APIView):
    """POST /api/v1/trainer/rate/ — rate a trainer."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TrainerRatingCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        rating = serializer.save()
        return Response(
            TrainerRatingSerializer(rating).data,
            status=status.HTTP_201_CREATED
        )


class MyTrainerRatingsView(APIView):
    """GET /api/v1/trainer/rating/me/ — ratings provided by the authenticated member."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            member = request.user.member
        except Exception:
            return Response({'error': 'Member profile not found'}, status=status.HTTP_404_NOT_FOUND)

        ratings = TrainerRating.objects.filter(
            member=member,
            is_deleted=False,
        ).select_related('trainer__user').order_by('-created_at')

        serializer = TrainerRatingSerializer(ratings, many=True)
        return Response(serializer.data)


# =============================================================================
# TRAINER INVITATION
# =============================================================================
class TrainerInvitationView(TrainerModelActions, ModelCRUDView):
    """CRUD for TrainerInvitation."""
    feature_key = 'instructors'
    feature_keys = ['trainer']
    queryset = TrainerInvitation.objects.select_related('invited_by').all()
    serializer_class = TrainerInvitationSerializer
    permission_classes = [HasFeatureMethodPermission]

    def _create(self, request):
        serializer = TrainerInvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = serializer.save()

        # Build invitation URL
        invite_url = f"{request.scheme}://{request.get_host()}/trainer/register?token={invitation.token}"

        # Resolve gym name from tenant context
        company_name = getattr(getattr(request, 'tenant', None), 'name', None) or 'Your Gym'
        invited_by_name = getattr(request.user, 'full_name', None) or getattr(request.user, 'email', '')

        # Send HTML email using the trainer invitation template
        try:
            from django.conf import settings
            from django.core.mail import EmailMultiAlternatives
            from django.template.loader import render_to_string

            context = {
                'company_name': company_name,
                'invited_by_name': invited_by_name,
                'invitation_url': invite_url,
                'expires_at': invitation.invitation_expires_at,
            }
            html_body = render_to_string('trainer/emails/trainer_invitation_email.html', context)
            fallback_text = (
                f"Hi,\n\n"
                f"{invited_by_name} has invited you to join {company_name} as a Trainer on Fitssort.\n\n"
                f"Complete your registration here:\n{invite_url}\n\n"
                f"This link expires on {invitation.invitation_expires_at}."
            )
            email = EmailMultiAlternatives(
                subject=f"You're invited to join {company_name} as a Trainer",
                body=fallback_text,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[invitation.invited_email],
            )
            email.attach_alternative(html_body, 'text/html')
            email.send(fail_silently=False)
        except Exception as e:
            return Response({
                'error': f'Invitation created but email failed: {str(e)}',
                'invitation_id': invitation.id,
                'invite_url': invite_url,
            }, status=status.HTTP_201_CREATED)

        return Response({
            'message': 'Invitation sent successfully',
            'invitation_id': invitation.id,
            'invite_url': invite_url,
        }, status=status.HTTP_201_CREATED)


class VerifyTrainerInvitationAPIView(APIView):
    """POST /api/v1/trainer/public/verify-invitation/ — verify invitation token."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyTrainerInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = TrainerInvitation.objects.get(token=serializer.validated_data['token'])
        return Response({
            'valid': True,
            'invitation_id': invitation.id,
            'email': invitation.invited_email,
        })


class CompleteTrainerRegistrationAPIView(APIView):
    """POST /api/v1/trainer/public/complete-registration/ — set password and create trainer."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CompleteTrainerRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        return Response({
            'message': 'Registration completed successfully',
            'trainer_id': profile.id,
            'username': profile.username,
        }, status=status.HTTP_201_CREATED)


class TrainerInsightsAPIView(APIView):
    """GET /api/v1/trainer/insights/ — trainer-focused dashboard metrics."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _get_trainer_profile_for_user(request.user)
        if profile is None:
            return Response({'error': 'Trainer profile not found'}, status=status.HTTP_404_NOT_FOUND)

        today = timezone.now().date()

        classes_qs = TrainerClass.objects.filter(trainer=profile, is_deleted=False)
        schedules_qs = TrainerSchedule.objects.filter(trainer=profile, is_deleted=False)
        upcoming_qs = schedules_qs.filter(scheduled_date__gte=today, is_cancelled=False)
        ratings_qs = TrainerRating.objects.filter(trainer=profile, is_deleted=False)

        avg_rating = ratings_qs.aggregate(avg=Avg('rating'))['avg'] or 0

        return Response({
            'trainer_id': profile.id,
            'total_classes': classes_qs.count(),
            'published_classes': classes_qs.filter(is_published=True).count(),
            'total_schedules': schedules_qs.count(),
            'upcoming_schedules': upcoming_qs.count(),
            'total_participants': schedules_qs.aggregate(total=Sum('current_participants'))['total'] or 0,
            'average_rating': round(float(avg_rating), 1) if avg_rating else 0,
            'total_ratings': ratings_qs.count(),
        })