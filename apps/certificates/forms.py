#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: ai ts=4 sts=4 et sw=4

import datetime

from django.forms import ModelForm
from django import forms
from django.forms.extras.widgets import SelectDateWidget
from models import DomainBoundCertificate, TrustAnchorCertificate
import datetime

from django.utils.translation import ugettext_lazy as _



class TrustAnchorCertificateForm(ModelForm):
    class Meta:
        model = TrustAnchorCertificate
        fields = ('email','dns', 'rsa_keysize', 'organization','city', 'state',
                   'expire_days','contact_first_name',
                  'contact_last_name', 'contact_email', 'contact_mobile_phone',
                  'contact_land_phone', 'contact_fax','npi',)
    required_css_class = 'required'
    
    def clean_email(self):
        email = self.cleaned_data.get('email', "")
        anchors = TrustAnchorCertificate.objects.filter(email=email, status="good").count()
        endpoints = DomainBoundCertificate.objects.filter(email=email, status="good").count()
        
        if anchors or endpoints:
            raise forms.ValidationError(_('A certifcate was already created with this email. It must be revoked before continuing.'))
        return email
    
    def clean_dns(self):
        dns = self.cleaned_data.get('dns', "")
        anchors = TrustAnchorCertificate.objects.filter(dns=dns, status="good").count()
        endpoints = DomainBoundCertificate.objects.filter(dns=dns, status="good").count()
        
        if anchors or endpoints:
            raise forms.ValidationError(_('A certifcate was already created with this DNS. It must be revoked before continuing.'))
        return dns
        
        
        
        
        
        
        
        if email:
            username = self.cleaned_data.get('username')
            if email and User.objects.filter(email=email).exclude(username=username).count():
                raise forms.ValidationError(_('This email address is already registered.'))
            return email
        else:
            return email


class RevokeTrustAnchorCertificateForm(ModelForm):
    class Meta:
        model = TrustAnchorCertificate
        fields = ('revoke',)
    required_css_class = 'required'



class DomainBoundCertificateForm(ModelForm):
    class Meta:
        model = DomainBoundCertificate
        fields = ('email', 'dns', 'rsa_keysize', 'organization','city', 'state', 
                  'expire_days', 'contact_first_name', 'contact_last_name',
                  'contact_email', 'contact_mobile_phone', 'contact_land_phone',
                  'contact_fax','npi',)
    required_css_class = 'required'
    
    def clean_email(self):
        email = self.cleaned_data.get('email', "")
        anchors = TrustAnchorCertificate.objects.filter(email=email, status="good").count()
        endpoints = DomainBoundCertificate.objects.filter(email=email, status="good").count()
        
        if anchors or endpoints:
            raise forms.ValidationError(_('A certifcate was already created with this email. It must be revoked before continuing.'))
        return email
    
    def clean_dns(self):
        dns = self.cleaned_data.get('dns', "")
        anchors = TrustAnchorCertificate.objects.filter(dns=dns, status="good").count()
        endpoints = DomainBoundCertificate.objects.filter(dns=dns, status="good").count()
        
        if anchors or endpoints:
            raise forms.ValidationError(_('A certifcate was already created with this DNS. It must be revoked before continuing.'))
        return dns
    
class RevokeDomainBoundCertificateForm(ModelForm):
    class Meta:
        model = DomainBoundCertificate
        fields = ('revoke',)
    required_css_class = 'required'