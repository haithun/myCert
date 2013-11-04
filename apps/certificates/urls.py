#!/usr/bin/env python
# -*- coding: utf-8 -*-

from django.conf.urls.defaults import patterns, include, url
from views import *


urlpatterns = patterns('',
   

    url(r'create-trust-anchor/', create_trust_anchor_certificate,
                       name="create_trust_anchor_certificate"),

    url(r'create-domain-bound/(?P<serial_number>\S+)', create_domain_certificate,
                       name="create_domain_certificate"),

    
    url(r'dashboard/', certificate_dashboard,
                       name="certificate_dashboard"),
    
    url(r'revoke-endpoint/(?P<serial_number>\S+)', revoke_domain_certificate,
                        name="revoke_domain_certificate"),    
    
    url(r'revoke-trust-anchor/(?P<serial_number>\S+)', revoke_trust_anchor_certificate,
                        name="revoke_trust_anchor_certificate"),    
    
    )
