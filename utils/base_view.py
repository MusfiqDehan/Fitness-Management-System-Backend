"""Reusable base view for standard CRUD + action dispatch.

Usage:
# utils/base_crud_view.py — already created

# apps/yourapp/views.py
from utils.base_crud_view import ModelCRUDView

class YourModelActions:
    actions = {
        'activate':   lambda self, req, pk: self._toggle_flag(YourModel, pk, 'is_active', True),
        'deactivate': lambda self, req, pk: self._toggle_flag(YourModel, pk, 'is_active', False),
        'restore':    lambda self, req, pk: self._restore(YourModel, pk),
    }

    def _toggle_flag(self, model, pk, field, value=None):
        try:
            obj = model.objects.get(pk=pk)
        except model.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        if value is None:
            value = not getattr(obj, field)
        setattr(obj, field, value)
        obj.save(update_fields=[field])
        return Response({'message': 'Done', field: value})


class YourModelView(YourModelActions, ModelCRUDView):
    feature_key = 'your_feature' # for permission checks
    queryset = YourModel.objects.all()
    serializer_class = YourModelSerializer
    permission_classes = [HasFeatureMethodPermission]

# URL dispatch (no pk = list/create, pk = retrieve/update/delete):
    GET    /resources/           → list
    POST   /resources/           → create
    GET    /resources/{pk}/     → retrieve
    PUT    /resources/{pk}/     → full update
    PATCH  /resources/{pk}/     → partial update
    DELETE /resources/{pk}/     → soft delete
    PATCH  /resources/{pk}/?action=activate|deactivate|...

"""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.generics import GenericAPIView


class ModelCRUDView(GenericAPIView):
    """
    Single view handling standard CRUD + resource-specific actions.

    HTTP Methods:
    - GET     /resources/           → list
    - POST    /resources/           → create
    - GET     /resources/{pk}/      → retrieve
    - PUT     /resources/{pk}/      → update (full)
    - PATCH   /resources/{pk}/      → update (partial)
    - DELETE  /resources/{pk}/      → soft delete

    Actions (routed by ?action=):
    - PATCH   /resources/{pk}/?action=activate   → activate
    - PATCH   /resources/{pk}/?action=deactivate → deactivate
    - PATCH   /resources/{pk}/?action=restore     → restore (soft-deleted)
    - PATCH   /resources/{pk}/?action=highlight   → toggle is_highlighted
    """
    actions = {}

    # GET /resources/ — list
    def get(self, request, pk=None, **kwargs):
        if pk is not None:
            return self._retrieve(pk)
        return self._list(request)

    # POST /resources/ — create  |  POST /resources/{pk}/?action=X — dispatch action
    def post(self, request, pk=None, **kwargs):
        if pk is not None:
            action = request.query_params.get('action')
            if action:
                return self._handle_action(pk, action, request)
            return self._update(pk, request, partial=False)
        return self._create(request)

    # PUT /resources/{pk}/ — full update
    def put(self, request, pk, **kwargs):
        return self._update(pk, request, partial=False)

    # PATCH /resources/{pk}/ — partial update
    def patch(self, request, pk, **kwargs):
        return self._update(pk, request, partial=True)

    # DELETE /resources/{pk}/ — soft delete
    def delete(self, request, pk, **kwargs):
        return self._destroy(pk)

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------
    def _list(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def _create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    def _retrieve(self, pk):
        instance = self.get_object()
        return Response(self.get_serializer(instance).data)

    def _update(self, pk, request, partial):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return Response(self.get_serializer(instance).data)

    def _destroy(self, pk):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _handle_action(self, pk, action, request):
        handler = self.actions.get(action)
        if not handler:
            return Response({'error': f'Unknown action: {action}'}, status=status.HTTP_400_BAD_REQUEST)
        return handler(self, request, pk)