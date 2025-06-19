from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("mark_post/", views.mark_post, name="mark_post"),
]