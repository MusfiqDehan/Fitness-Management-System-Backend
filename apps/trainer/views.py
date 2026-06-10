from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Avg, Sum
from django.utils import timezone
from django.conf import settings
import secrets

from utils.base_view import ModelCRUDView
from utils.list_mixins import BranchScopedListMixin, SearchFilterSortPaginationMixin
from utils.limits import branch_capacity_exceeded, total_capacity_exceeded
from utils.tenancy_helpers import get_branch_manager_scope_ids as _branch_manager_scope_ids
from apps.access.permissions import HasFeatureMethodPermission
from apps.access.utils import user_can
from apps.crm.email_delivery import resolve_tenant_mail_route
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
class TrainerProfileView(BranchScopedListMixin, TrainerModelActions, ModelCRUDView):
    """CRUD for TrainerProfile + actions."""
    feature_key = 'instructors'
    feature_keys = ['trainer']
    queryset = TrainerProfile.objects.select_related('user').all()
    serializer_class = TrainerProfileSerializer
    permission_classes = [IsTrainerOrFeaturePermission]
    branch_scope_field = 'branch_id'
    filterset_fields = ['branch', 'is_active', 'is_highlighted', 'is_published']
    search_fields = ['user__full_name', 'user__email', 'username', 'title']
    ordering_fields = ['id', 'user__full_name', 'average_rating', 'experience_years', 'created_at']
    ordering = ['id']

    actions = {
        'recalc': lambda self, req, pk: self._recalc(req, pk),
        'activate': lambda self, req, pk: self._toggle_trainer_active(req, pk, True),
        'deactivate': lambda self, req, pk: self._toggle_trainer_active(req, pk, False),
    }

    def _toggle_trainer_active(self, request, pk, value):
        try:
            profile = self.get_queryset().get(pk=pk)
        except TrainerProfile.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        user = profile.user
        user.is_active = value
        user.save(update_fields=['is_active'])
        return Response({
            'message': 'Activated' if value else 'Deactivated',
            'is_active': value,
        })

    def get_queryset(self):
        queryset = super().get_queryset()
        if _is_trainer_user(self.request.user):
            queryset = queryset.filter(user=self.request.user)
        return self.scope_branch_queryset(queryset)

    def _create(self, request):
        if _is_trainer_user(request.user):
            return Response({'error': 'Trainer profiles are created through invitation flow only.'}, status=status.HTTP_403_FORBIDDEN)

        payload = request.data.copy()
        scope_ids = _branch_manager_scope_ids(request.user)
        if scope_ids is not None:
            if not scope_ids:
                return Response(
                    {'detail': 'No managed branch is configured for this account.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            incoming_branch_id = payload.get('branch_id') or payload.get('branch')
            if incoming_branch_id is None:
                payload['branch'] = scope_ids[0]
            else:
                try:
                    incoming_branch_int = int(incoming_branch_id)
                except (TypeError, ValueError):
                    return Response({'detail': 'Invalid branch selection.'}, status=status.HTTP_400_BAD_REQUEST)
                if incoming_branch_int not in scope_ids:
                    return Response(
                        {'detail': 'You can only create trainers in your managed branch.'},
                        status=status.HTTP_403_FORBIDDEN,
                    )

        total_limit_error = total_capacity_exceeded(
            TrainerProfile.objects,
            'max_users',
            limit_type='trainers',
        )
        if total_limit_error is not None:
            return Response(total_limit_error, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

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
class TrainerDocumentView(SearchFilterSortPaginationMixin, TrainerModelActions, ModelCRUDView):
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
class TrainerClassView(SearchFilterSortPaginationMixin, TrainerModelActions, ModelCRUDView):
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
class TrainerScheduleView(SearchFilterSortPaginationMixin, TrainerModelActions, ModelCRUDView):
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
class TrainerRatingView(SearchFilterSortPaginationMixin, TrainerModelActions, ModelCRUDView):
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
def _send_trainer_invitation_email(invitation, request, force_new_token=False) -> str:
    """Send trainer invitation email. Returns invite URL."""
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string

    now = timezone.now()
    if force_new_token or invitation.is_expired():
        invitation.token = secrets.token_urlsafe(48)
        invitation.invitation_expires_at = now + timezone.timedelta(days=7)
        invitation.save(update_fields=['token', 'invitation_expires_at', 'updated_at'])

    invite_url = f"{request.scheme}://{request.get_host()}/trainer/register?token={invitation.token}"
    company_name = getattr(getattr(request, 'tenant', None), 'name', None) or 'Your Gym'
    invited_by_name = getattr(getattr(request, 'user', None), 'full_name', None) or getattr(
        getattr(request, 'user', None), 'email', ''
    )

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
    tenant = getattr(request, 'tenant', None)
    from_email, connection = resolve_tenant_mail_route(tenant)
    email = EmailMultiAlternatives(
        subject=f"You're invited to join {company_name} as a Trainer",
        body=fallback_text,
        from_email=from_email,
        to=[invitation.invited_email],
        connection=connection,
    )
    email.attach_alternative(html_body, 'text/html')
    try:
        email.send(fail_silently=False)
    except Exception:
        fallback_email = EmailMultiAlternatives(
            subject=f"You're invited to join {company_name} as a Trainer",
            body=fallback_text,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@gym.local'),
            to=[invitation.invited_email],
        )
        fallback_email.attach_alternative(html_body, 'text/html')
        fallback_email.send(fail_silently=False)

    return invite_url


class TrainerInvitationView(BranchScopedListMixin, TrainerModelActions, ModelCRUDView):
    """CRUD for TrainerInvitation."""
    feature_key = 'instructors'
    feature_keys = ['trainer']
    queryset = TrainerInvitation.objects.select_related('invited_by').all()
    serializer_class = TrainerInvitationSerializer
    permission_classes = [HasFeatureMethodPermission]
    branch_scope_field = 'branch_id'
    filterset_fields = ['branch', 'is_active', 'is_published']
    search_fields = ['invited_email', 'full_name', 'phone_number']
    ordering_fields = ['id', 'created_at', 'invited_email', 'full_name']
    ordering = ['id']

    actions = {
        'resend': lambda self, req, pk: self._resend_invitation(req, pk),
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        return self.scope_branch_queryset(queryset)

    def _resend_invitation(self, request, pk):
        try:
            invitation = self.get_queryset().get(pk=pk)
        except TrainerInvitation.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

        if invitation.accepted_at:
            return Response(
                {'detail': 'Invitation has already been accepted.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not invitation.invited_email:
            return Response(
                {'detail': 'Invitation does not have an email address.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            invite_url = _send_trainer_invitation_email(
                invitation,
                request,
                force_new_token=True,
            )
        except Exception as exc:
            return Response(
                {'error': f'Failed to send invitation email: {str(exc)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'message': 'Invitation resent successfully',
            'invitation_sent': True,
            'invite_url': invite_url,
        })

    def _create(self, request):
        payload = request.data.copy()
        scope_ids = _branch_manager_scope_ids(request.user)
        if scope_ids is not None:
            if not scope_ids:
                return Response(
                    {'detail': 'No managed branch is configured for this account.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            incoming_branch_id = payload.get('branch_id') or payload.get('branch')
            if incoming_branch_id is None:
                payload['branch_id'] = scope_ids[0]
            else:
                try:
                    incoming_branch_int = int(incoming_branch_id)
                except (TypeError, ValueError):
                    return Response({'detail': 'Invalid branch selection.'}, status=status.HTTP_400_BAD_REQUEST)
                if incoming_branch_int not in scope_ids:
                    return Response(
                        {'detail': 'You can only invite trainers to your managed branch.'},
                        status=status.HTTP_403_FORBIDDEN,
                    )

        total_limit_error = total_capacity_exceeded(
            TrainerProfile.objects,
            'max_users',
            limit_type='trainers',
        )
        if total_limit_error is not None:
            return Response(total_limit_error, status=status.HTTP_403_FORBIDDEN)

        branch_id = payload.get('branch_id') or payload.get('branch')
        limit_error = branch_capacity_exceeded(
            TrainerProfile.objects,
            branch_id,
            'max_trainers_per_branch',
            limit_type='trainers_per_branch',
        )
        if limit_error is not None:
            return Response(limit_error, status=status.HTTP_403_FORBIDDEN)

        serializer = TrainerInvitationCreateSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        invitation = serializer.save()

        try:
            invite_url = _send_trainer_invitation_email(invitation, request)
        except Exception as e:
            invite_url = f"{request.scheme}://{request.get_host()}/trainer/register?token={invitation.token}"
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
            'branch_id': invitation.branch_id,
            'branch_name': invitation.branch.name if invitation.branch_id else None,
        })


class CompleteTrainerRegistrationAPIView(APIView):
    """POST /api/v1/trainer/public/complete-registration/ — set password and create trainer."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CompleteTrainerRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()

        try:
            from apps.reminder.utils import create_notification
            # Broadcast to admins: a new trainer joined
            create_notification(
                notification_type='trainer_onboarded',
                title=f'New trainer joined: {profile.user.full_name or profile.username}',
                actor_name=profile.user.full_name or '',
                actor_email=profile.user.email or '',
                target_type='trainer',
                target_id=str(profile.id),
            )
            # Personal to the new trainer: welcome message
            create_notification(
                notification_type='welcome_trainer',
                title=f'Welcome to the team, {profile.user.full_name or profile.username}!',
                message='Your trainer profile is ready. Start adding your classes and schedules.',
                recipient=profile.user,
                target_type='trainer',
                target_id=str(profile.id),
            )
        except Exception:
            pass  # Notifications are best-effort

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