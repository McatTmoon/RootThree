from django.urls import path, re_path
from . import views, callbacks, student_views

app_name = "bloodnet"

urlpatterns = [
    # Student Blood Donation Frontend Pages
    path("", student_views.home_page, name="home"),
    path("index.html", student_views.home_page, name="index_html"),
    re_path(r"^registration/?$", student_views.registration_page, name="registration"),
    re_path(r"^invitation/?$", student_views.invitation_page, name="invitation"),
    re_path(r"^tracking/?$", student_views.tracking_page, name="tracking"),
    re_path(r"^tracking/(?P<tracking_code>[^/]+)/?$", student_views.tracking_page, name="tracking_detail"),
    re_path(r"^images/logo\.png$", student_views.serve_logo_asset, name="logo_asset"),

    # Official BloodNet Hospital API & Simulator Callbacks
    re_path(r"^health/?$", views.health, name="health"),
    re_path(r"^requests/?$", views.requests_collection, name="requests_collection"),
    re_path(r"^requests/(?P<request_id>[^/]+)/approve/?$", views.request_approve, name="request_approve"),
    re_path(r"^requests/(?P<request_id>[^/]+)/cancel/?$", views.request_cancel, name="request_cancel"),
    re_path(r"^requests/(?P<request_id>[^/]+)/amend/?$", views.request_amend, name="request_amend"),
    re_path(r"^requests/(?P<request_id>[^/]+)/?$", views.request_detail, name="request_detail"),
    re_path(r"^callbacks/gateway-status/?$", callbacks.callback_gateway_status, name="callback_gateway_status"),
    re_path(r"^callbacks/donor-response/?$", callbacks.callback_donor_response, name="callback_donor_response"),
    re_path(r"^callbacks/donor-progress/?$", callbacks.callback_donor_progress, name="callback_donor_progress"),
]
