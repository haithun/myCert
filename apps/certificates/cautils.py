#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: ai ts=4 sts=4 et sw=4

from django.conf import settings
from django.utils.datastructures import SortedDict
import os, sys, uuid, json, re
from shutil import copyfile, copytree, rmtree
from subprocess import call
import pdb
from sha import sha256_from_filepath
from cStringIO import StringIO
import subprocess
from datetime import datetime
from fileutils import SimpleS3


def write_verification_message(serial_number, common_name, status,
                               cert_sha1_fingerprint,
                               note = ""):

    d = SortedDict()
    d['SerialNumber']        = serial_number
    d['CommonName']          = common_name
    d['CertStatus']          = status
    d['CertSHA1Fingerprint'] = cert_sha1_fingerprint 
    d['ThisUpdate']          = str(datetime.now())
    
    if note:
        d['Note']            = note
    
    return json.dumps(d, indent =4)


def extract(raw_string, start_marker, end_marker):
    start = raw_string.index(start_marker) + len(start_marker)
    end = raw_string.index(end_marker, start)
    return raw_string[start:end]

def chain_keys_in_list(outpath, filenames):
    certslist_str = ""
    with open(outpath, 'w') as outfile:
        for fname in filenames:
            with open(fname) as infile:
                outfile.write(infile.read())

    f = open(outpath, 'r')
    certslist_str = f.read()
    f.close()

    list_of_certs = re.findall('-----BEGIN CERTIFICATE-----$\n(.*?)\n^-----END CERTIFICATE-----',
               certslist_str, re.DOTALL|re.MULTILINE)
    
    #print "LIST O CERTS", list_of_certs
    newcerts =[]
    for c in list_of_certs:
        nc = c.replace('\n','')
        newcerts.append(nc)
    return newcerts





def write_x5c_message(name, x5ckeys):
    jose_x509 = {"keys":[
                {"kty":"PKIX",
                "x5c": x5ckeys,
                    "use":"sig",
                    "kid":name }]
                }
    return json.dumps(jose_x509, indent =4)





def build_crl():
    password = "pass:" + settings.PRIVATE_PASSWORD
    crl_file = os.path.join(settings.CA_CRL_DIR, settings.CRL_FILENAME)
    call(["openssl", "ca", "-config",  settings.CA_MAIN_CONF ,  "-gencrl", "-out",
          crl_file, "-passin", password])
    
    if settings.USE_S3:
        s=SimpleS3()
        key = "crl/" + settings.CRL_FILENAME
        url = s.store_in_s3(key, crl_file,
                        bucket=settings.CRL_BUCKET, public=True)
    if url:
        print "Completed upload @ %s. Archive URL = %s" % (datetime.now(), url)
    else:
        print "Upload failed @ %s"
        url= "Failed"
        
    return url


def build_anchor_crl(trust_anchor):
    config_file = "%s-crl-stub.cnf" % (trust_anchor.dns)
    crl_file = "%s.crl" % (trust_anchor.dns)
    crl_path = os.path.join(trust_anchor.completed_dir_path, crl_file)
    crl_conf = os.path.join(trust_anchor.completed_dir_path, config_file)
    call(["openssl", "ca", "-config",  crl_conf,  "-gencrl", "-out", crl_path,])
    
    if settings.USE_S3:
        s=SimpleS3()
        key = "crl/" + crl_file
        url = s.store_in_s3(key, crl_path,
                        bucket=settings.CRL_BUCKET, public=True)
    if url:
        print "Completed upload @ %s. Archive URL = %s" % (datetime.now(), url)
    else:
        print "Upload failed @ %s"
        url= "Failed"
        
    return url


def revoke(cert):

    #TODO Find a more secure way to store password.
    password = "pass:" + settings.PRIVATE_PASSWORD 
    fn = cert.serial_number + ".pem"
    fn = os.path.join(settings.CA_SIGNED_DIR, fn)
    error, output = subprocess.Popen(["openssl", "ca",
                                      "-config", settings.CA_MAIN_CONF,
                                      "-revoke" , fn,
                                      "-passin", password ],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    if os.path.exists(cert.completed_dir_path):
        rmtree(cert.completed_dir_path)
        #print "DELETED the path", cert.completed_dir_path
    return output

def revoke_from_anchor(cert):

    fn = cert.serial_number + ".pem"
    fn = os.path.join(settings.CA_SIGNED_DIR, fn)
    
    config_file = "%s/%sdomain-bound-stub.cnf" % (cert.completed_dir_path,
                                                  cert.dns,)

    error, output = subprocess.Popen(["openssl", "ca", "-config", config_file,
                                      "-revoke" , fn],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    
    if os.path.exists(cert.completed_dir_path):
        rmtree(cert.completed_dir_path)
        # print "DELETED the path", cert.completed_dir_path
    return output



def create_trust_anchor_certificate(common_name     = "example.com",
                                    email           = "example.com",
                                    dns             = "example.com",
                                    expires         = 1095,
                                    organization    = "NIST",
                                    city            = "Gaithersburg",
                                    state           = "MD",
                                    country         = "US",
                                    rsakey          = 2048,
                                    user            = "alan",):
    #a  dict for all the things we want to return
    result = {  "sha256_digest":                      "",
                "anchor_zip_download_file_name":      "",
                "status":                             "failed",
                "serial_number":                      "-01",
                "sha1_fingerprint":                   "",
                "private_key_path":                   "",
                "public_key_path":                    "",
                "notes":                              "Certificate generation in process.",
                "completed_dir_path":                 ""}
    
    
    dirname = str(uuid.uuid4())[0:5]
    tname =  dns
    keysize = "rsa:" + str(rsakey)
    csrname = tname + ".csr"
    privkeyname = tname + "Key.key"         # Private key in pem format
    PCKS8privkeyname  = tname + "Key.der"   # PCKS8 DER formatted private key file
    p12name = tname + ".p12"                # p12 formatted private and public keys
    public_cert_name =  tname + ".pem"      #pubic certificate as a PEM
    public_cert_name_der =  tname + ".der"  # pubic certificate as a der
    anchor_zip_download_file_name = tname + "-ANCHOR.zip"
    conf_stub_file_name = tname  + "trust-anchor-stub.cnf"
    crl_conf_stub_file_name = tname  + "crl.cnf"
    completed_user_dir = os.path.join(settings.CA_COMPLETED_DIR, user )
    completed_user_anchor_dir = os.path.join(completed_user_dir, "anchors")
    completed_user_dom_bound_dir = os.path.join(completed_user_dir, "endoints")
    completed_this_anchor_dir = os.path.join(completed_user_anchor_dir,
                                             str(uuid.uuid4()) ,dns)

    
    subj = '/emailAddress=' + email + \
           '/C='            + country +  \
           '/ST='           + state + \
           '/L='            + city + \
           '/CN='           + common_name + \
           '/O='            + organization
    
    os.chdir("/opt/ca/inprocess/anchors")
    os.umask(0000)
    os.mkdir(dirname)
    os.chdir(dirname)
    
    #Create the signing request. ----------------------------------------------
    error, output  = subprocess.Popen(["openssl", "req", "-subj", subj , "-out", csrname,
                             "-new", "-newkey", keysize, "-nodes", "-keyout",
                             privkeyname],
                            stdout = subprocess.PIPE,
                            stderr= subprocess.PIPE,
                            ).communicate()
    print output
    
    
    #get the next serial number ------------------------------------------------
    fp = open("/opt/ca/conf/serial", "r")
    serial = str(fp.read())
    fp.close()
    
    
    # Copy a stub config file to our directory----------------------------------
    copyfile(os.path.join(settings.CA_CONF_DIR, "trust-anchor-stub.cnf"), conf_stub_file_name)
    
    # Prepare strings for sed, that will be used to fillout our stub into a usable config file.
    
    #Prepare sed strings
    seddns = "s/|DNS|/%s/g" % (dns)
    seddays = "s/|DAYS|/%s/g" % (expires)
    sedserial = "s#|SERIAL|#%s#g" % (serial[:-1])
    sedcountry = "s#|COUNTRY|#%s#g" % (country)
    sedstate= "s#|STATE|#%s#g" % (state)
    sedcity = "s#|CITY|#%s#g" % (city)
    sedcommon_name =  "s#|COMMON_NAME|#%s#g" % (common_name)
    sedorganization = "s#|ORGANIZATION|#%s#g" % (organization)
    sedemail = "s#|EMAIL_ADDRESS|#%s#g" % (email)
    
    
    #Apply the sed operations --------------------------------------------------- 
    error, output = subprocess.Popen(["sed", "-i", "-e", seddns,  conf_stub_file_name],
                                stdout=subprocess.PIPE,
                                stderr= subprocess.PIPE
                                ).communicate()
    error, output = subprocess.Popen(["sed", "-i", "-e", seddays, conf_stub_file_name],
                                stdout=subprocess.PIPE,
                                stderr= subprocess.PIPE
                                ).communicate()    
    error, output = subprocess.Popen(["sed", "-i", "-e", sedserial, conf_stub_file_name],
                                stdout=subprocess.PIPE,
                                stderr= subprocess.PIPE
                                ).communicate()  
    error, output = subprocess.Popen(["sed", "-i", "-e", sedcountry,
                                      conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    
    error, output = subprocess.Popen(["sed", "-i", "-e", sedstate,
                                      conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()

    error, output = subprocess.Popen(["sed", "-i", "-e", sedcity,
                                      conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()

    error, output = subprocess.Popen(["sed", "-i", "-e", sedcommon_name,
                                      conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    error, output = subprocess.Popen(["sed", "-i", "-e", sedorganization,
                                      conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    
    error, output = subprocess.Popen(["sed", "-i", "-e", sedemail,
                                      conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    
    
    
    
    # Build the certificate from the signing request.
    
    
    
    
    
    
    
    password = "pass:" + settings.PRIVATE_PASSWORD #TODO Find a more secure way to do this
    #
    error, signoutput = subprocess.Popen(["openssl", "ca", "-batch", "-config",
                             conf_stub_file_name, "-in", csrname, "-out",
                             public_cert_name, "-passin", password],
                             stdout=subprocess.PIPE,
                             stderr= subprocess.PIPE
                            ).communicate()

    #print "CERT SIGN OUT", signoutput
    
    #if the previous step fails, then 
    if str(output.lower()).__contains__("failed to update database"):
        print "PUBLIC CERT NAME:", public_cert_name, "FAILED!!!!"
        result["status"]                            = "failed"
        result["notes"] = signoutput
        os.chdir(settings.BASE_DIR) 
        return result
        
    
    #get the serial number
    
    output,error = subprocess.Popen(["openssl", "x509", "-in",
                                      public_cert_name, "-serial","-noout",],
                             stdout=subprocess.PIPE,
                             stderr= subprocess.PIPE
                            ).communicate()
    
    try:
        serialsplit = output.split("=")
        serial_number = str(serialsplit[1])[:-1]
    except(IndexError):
        result["status"] = "failed"
        result["notes"] = output
        os.chdir(settings.BASE_DIR) 
        return result
        
    
    #print "SERIAL:",  serial_number
    sedserial = "s#|SERIAL|#%s#g" % (serial_number)
    #get the sha1 fingerprint
    output,error = subprocess.Popen(["openssl", "x509", "-in",
                                      public_cert_name, "-fingerprint","-noout",],
                             stdout=subprocess.PIPE,
                             stderr= subprocess.PIPE
                            ).communicate()
    
    

    fpsplit = output.split("=")
    sha1_fingerprint = str(fpsplit[1])[:-1]
    #print "SHA1 Fingerprint:",  sha1_fingerprint
    
    
    
    # Convert the public pem into a der
    error, output = subprocess.Popen(["openssl", "x509", "-outform", "der", "-in",
                                      public_cert_name, "-out",
                                      public_cert_name_der],
                             stdout=subprocess.PIPE,
                             stderr= subprocess.PIPE
                            ).communicate()
    

    
    
    error, output = subprocess.Popen(["openssl", "x509", "-outform", "der",
                                      "-in", public_cert_name, "-out",
                                      public_cert_name_der],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    

    # Convert the private key in pem format to a PCKS8 DER formatted private key file
    error, output = subprocess.Popen(["openssl", "pkcs8", "-topk8", "-out",
                                      PCKS8privkeyname,  "-in", privkeyname,
                                      "-inform", "pem", "-outform", "der",
                                      "-nocrypt",],
                             stdout=subprocess.PIPE,
                             stderr= subprocess.PIPE
                            ).communicate()
    
    
    #create the sha1 digest of the DER.
    sha256_digest = sha256_from_filepath(public_cert_name_der)
  
    #Create an empty index file
    if not os.path.exists('index'):
        open('index', 'w').close()
       

    #Since the anchor creation process completed, then build out the perm dirs
    if not os.path.exists(completed_user_dir):
        os.makedirs(completed_user_dir)
    
    if not os.path.exists(completed_user_anchor_dir):
        os.makedirs(completed_user_anchor_dir)
        
        
    completed_this_anchor_dir = os.path.join(completed_user_anchor_dir, dns)

    if os.path.exists(completed_this_anchor_dir):
        rmtree(completed_this_anchor_dir)
    copytree(".", completed_this_anchor_dir)
        
    os.chdir(completed_this_anchor_dir)
    error, output = subprocess.Popen(["zip", anchor_zip_download_file_name,
                                      public_cert_name, public_cert_name_der],
                                    stdout=subprocess.PIPE,
                                    stderr= subprocess.PIPE
                                    ).communicate()
    
    #Private Key Path for PEM
    private_key_path_pem = os.path.join(completed_this_anchor_dir, privkeyname)
    public_key_path_pem = os.path.join(completed_this_anchor_dir, public_cert_name)
    
    
    #build result dict
    result.update({"sha256_digest": sha256_digest,
                   "anchor_zip_download_file_name": anchor_zip_download_file_name,
                   "notes": "",
                   "serial_number" : serial_number,
                   "status": "unverified",
                   "sha1_fingerprint": sha1_fingerprint,
                   "private_key_path": private_key_path_pem,
                   "public_key_path": public_key_path_pem,
                   "completed_dir_path": completed_this_anchor_dir,
                   })
    
    
    
    # Get back to the directory we started.
    os.chdir(settings.BASE_DIR) 

    return result
    


def create_endpoint_certificate(common_name     = "foo.bar.org",
                                    email           = "foo.bar.org",
                                    dns             = "foo.bar.org",
                                    anchor_dns      = "bar.org",
                                    expires         = 1095,
                                    organization    = "NIST",
                                    city            = "Gaithersburg",
                                    state           = "MD",
                                    country         = "US",
                                    rsakey          = 4096,
                                    user            = "",
                                    private_key_path = "",
                                    public_key_path  = "",
                                    completed_anchor_dir = ""):
    
    result = {  "sha256_digest":                      "",
                "anchor_zip_download_file_name":      "",
                "status":                             "failed",
                "serial_number":                      "-01",
                "sha1_fingerprint":                   "",
                "private_key_path":                   "",
                "public_key_path":                    "",
                "notes":                              "Certificate generation in process.",
                "completed_dir_path":                 ""}
    
    dirname = str(uuid.uuid4())[0:5]
    tname =  dns
    keysize = "rsa:" + str(rsakey)
    csrname = tname + ".csr"
    privkeyname = tname + "Key.key"         # Private key in pem format
    PCKS8privkeyname  = tname + "Key.der"   # PCKS8 DER formatted private key file
    p12name = tname + ".p12"                # p12 formatted private and public keys
    public_cert_name =  tname + ".pem"      #pubic certificate as a PEM
    public_cert_name_der =  tname + ".der"  # pubic certificate as a der
    conf_stub_file_name = tname  + "domain-bound-stub.cnf"
    anchor_zip_download_file_name = str(uuid.uuid4()) + "-" + tname + "-ENDPOINT.zip"
    
    


    completed_user_dir = os.path.join(settings.CA_COMPLETED_DIR, user )
    completed_endpoint_dir = os.path.join(completed_anchor_dir, "endpoints/")

    completed_this_endpoint = os.path.join(completed_endpoint_dir, dns, )
    print "Email is ", email
   
    
    subj = '/emailAddress=' + email + \
           '/C='            + country +  \
           '/ST='           + state + \
           '/L='            + city + \
           '/CN='           + common_name + \
           '/O='            + organization 
    
    dirpath = os.path.join(settings.CA_INPROCESS_DIR, "domain-bound", dirname)
    os.umask(0000)
    os.mkdir(dirpath)
    os.chdir(dirpath)
     
    #print "Temp DIRECTORY is:",  dirpath
    #print "Temp DIRECTORY is:",  completed_this_domain_bound_dir
    
    #Determine if this is address or domain bound
    email_bound=False
    if email.__contains__("@"):
        email_bound=True
    
    # Create the signing request.
    call(["openssl", "req", "-subj", subj , "-out", csrname, "-new", "-newkey",
          keysize, "-nodes", "-keyout", privkeyname]) 
    
    # Copy a stub config file to our directory
    if email.__contains__("@"):
        copyfile(os.path.join(settings.CA_CONF_DIR,"email-bound-stub.cnf"),
                    conf_stub_file_name)
    else:
        copyfile(os.path.join(settings.CA_CONF_DIR,"domain-bound-stub.cnf"),
                    conf_stub_file_name)
    
    
    #get the next serial number
    fp = open("/opt/ca/conf/serial", "r")
    serial = str(fp.read())
    fp.close()
    
    # Modify the stub file
    seddns = "s/|DNS|/%s/g" % (dns)
    sedanchordns = "s/|ANCHORDNS|/%s/g" % (anchor_dns)
    
    sedcompletedanchordir = "s#|COMPLETED_ANCHOR_DIR|#%s#g" % (completed_anchor_dir)
    seddays = "s/|DAYS|/%s/g" % (expires)
    sedpublickey = "s#|CERTIFICATE|#%s#g" % (public_key_path)
    sedprivatekey = "s#|PRIVATE_KEY|#%s#g" % (private_key_path)
    sedserial = "s#|SERIAL|#%s#g" % (serial[:-1])
    sedcountry = "s#|COUNTRY|#%s#g" % (country)
    sedstate= "s#|STATE|#%s#g" % (state)
    sedcity = "s#|CITY|#%s#g" % (city)
    sedcommon_name =  "s#|COMMON_NAME|#%s#g" % (common_name)
    sedorganization = "s#|ORGANIZATION|#%s#g" % (organization)
    sedemail = "s#|EMAIL_ADDRESS|#%s#g" % (email)



    error, output = subprocess.Popen(["sed", "-i", "-e", sedcompletedanchordir,
                                      conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()


    error, output = subprocess.Popen(["sed", "-i", "-e", seddns,
                                      conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    
    error, output = subprocess.Popen(["sed", "-i", "-e", sedanchordns,
                                      conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    
    
    
    error, output = subprocess.Popen(["sed", "-i", "-e",
                                      seddays, conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    
    error, output = subprocess.Popen(["sed", "-i", "-e",
                                      sedpublickey, conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    
    error, output = subprocess.Popen(["sed", "-i", "-e",
                                      sedprivatekey, conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()

    error, output = subprocess.Popen(["sed", "-i", "-e", sedserial, conf_stub_file_name],
                                stdout=subprocess.PIPE,
                                stderr= subprocess.PIPE
                                ).communicate()      

    
    
    error, output = subprocess.Popen(["sed", "-i", "-e", sedcountry,
                                      conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    
    error, output = subprocess.Popen(["sed", "-i", "-e", sedstate,
                                      conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()

    error, output = subprocess.Popen(["sed", "-i", "-e", sedcity,
                                      conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()

    error, output = subprocess.Popen(["sed", "-i", "-e", sedcommon_name,
                                      conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    error, output = subprocess.Popen(["sed", "-i", "-e", sedorganization,
                                      conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    
    error, output = subprocess.Popen(["sed", "-i", "-e", sedemail,
                                      conf_stub_file_name],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    
    
    # Build the certificate from the signing request.
    
    error, signoutput = subprocess.Popen(["openssl", "ca", "-batch", "-config",
                             conf_stub_file_name, "-in", csrname, "-out",
                             public_cert_name],
                             stdout=subprocess.PIPE,
                             stderr= subprocess.PIPE
                            ).communicate()
  
    print "Signing ----------------", output
    
    #if the previous step fails, then 
    if str(output.lower()).__contains__("failed to update database") or \
       str(output).__contains__("unable to load CA private key"):
        print "PUBLIC CERT NAME:", public_cert_name, "FAILED!!!!"

        result["status"] = "failed"
        result["notes"]  = signoutput
        os.chdir(settings.BASE_DIR) 
        return result
        
    
    #get the serial number
    
    output,error = subprocess.Popen(["openssl", "x509", "-in",
                                      public_cert_name, "-serial","-noout",],
                             stdout=subprocess.PIPE,
                             stderr= subprocess.PIPE
                            ).communicate()
    
    
    try:
        serialsplit = output.split("=")
        serial_number = str(serialsplit[1])[:-1]
    except (IndexError):
        result["status"] = "failed"
        result["notes"]  = signoutput
        os.chdir(settings.BASE_DIR) 
        return result
    
    
    print "SERIAL:",  serial_number
    
    #get the sha1 fingerprint
    output,error = subprocess.Popen(["openssl", "x509", "-in",
                                      public_cert_name, "-fingerprint","-noout",],
                             stdout=subprocess.PIPE,
                             stderr= subprocess.PIPE
                            ).communicate()
    

    fpsplit = output.split("=")
    sha1_fingerprint = str(fpsplit[1])[:-1]
    #print "SHA1 Fingerprint:",  sha1_fingerprint
    
    
    # Convert the public pem into a der
    print "Convert the public pem into a der"
    output,error = subprocess.Popen(["openssl", "x509", "-outform", "der", "-in",
                                     public_cert_name, "-out",
                                     public_cert_name_der],
                             stdout=subprocess.PIPE,
                             stderr= subprocess.PIPE
                            ).communicate()
    
    #print "convert the private key in pem format to PCKS8 DER formatted private key file"
    #convert the private key in pem format to PCKS8 DER formatted private key file
    output,error = subprocess.Popen(["openssl", "pkcs8", "-topk8", "-out",
                                     PCKS8privkeyname,  "-in", privkeyname,
                                     "-inform", "pem", "-outform", "der",
                                     "-nocrypt",],
                             stdout=subprocess.PIPE,
                             stderr= subprocess.PIPE
                            ).communicate()

    
    # Create a p12 file from our der public key and out DER private key
    
    #print "openssl " + "pkcs12 " + "-export " + "-out " + p12name + " -inkey " + \
    #        privkeyname + " -in " +  PCKS8privkeyname + " -certfile " + public_key_path
    # call(["openssl", "pkcs12", "-export", "-out", p12name, "-inkey",  privkeyname,
    #      "-in",  PCKS8privkeyname, "-certfile",  caCertfile ])

    
    #print "# Create a p12 file from our der public key and out DER private key"

    
    output,error = subprocess.Popen(["openssl", "pkcs12", "-export", "-inkey",
                                     privkeyname, "-in", public_cert_name,
                                     "-out", p12name, "-passout", "pass:"],
                             stdout=subprocess.PIPE,
                             stderr= subprocess.PIPE
                            ).communicate()
    #print output, error
    

    
    #create the sha1 digest of the DER.
    sha256_digest = sha256_from_filepath(public_cert_name_der)
  

    #Since the anchor creation process completed, then built out the perm dirs
    
    
    
    print "--------------------------------------------------------------"
    if not os.path.exists(completed_endpoint_dir):
        os.makedirs(completed_endpoint_dir)
    
    if os.path.exists(completed_this_endpoint):
        rmtree(completed_this_endpoint)
        
    copytree(".", completed_this_endpoint)
        
    os.chdir(completed_this_endpoint)
    
    crl_conf = os.path.join(completed_anchor_dir, "crl.cnf" )
    
    print "crl_conf = ", crl_conf
    #if a crl.cnf does not exist, then create it.
    if not os.path.exists(crl_conf):
        print conf_stub_file_name
        copyfile(conf_stub_file_name, crl_conf)
        
    
    
    
    #create the zip file containing the private and public keys)
    error, output = subprocess.Popen(["zip", anchor_zip_download_file_name,
                                      public_cert_name, public_cert_name_der,
                                      privkeyname, PCKS8privkeyname, p12name
                                      ],
                                    stdout=subprocess.PIPE,
                                    stderr= subprocess.PIPE
                                    ).communicate()
    
    #Private Key Path for PEM
    private_key_path_pem = os.path.join(completed_this_endpoint, privkeyname)
    public_key_path_pem = os.path.join(completed_this_endpoint,  public_cert_name)

    
    #build result dict
    result.update({"sha256_digest":  sha256_digest,
                   "anchor_zip_download_file_name": anchor_zip_download_file_name,
                   "notes": "",
                   "serial_number" : serial_number,
                   "status": "unverified",
                   "sha1_fingerprint": sha1_fingerprint,
                   "private_key_path": private_key_path_pem,
                   "public_key_path": public_key_path_pem,
                   "completed_dir_path" :completed_this_endpoint
                   })
    
    # Get back to the directory we started.
    os.chdir(settings.BASE_DIR) 

    return result




















def create_crl_conf(common_name     = "foo.bar.org",
                    email           = "foo.bar.org",
                    dns             = "foo.bar.org",
                    anchor_dns      = "bar.org",
                    expires         = 1095,
                    organization    = "NIST",
                    city            = "Gaithersburg",
                    state           = "MD",
                    country         = "US",
                    rsakey          = 4096,
                    user            = "",
                    private_key_path = "",
                    public_key_path  = "",
                    completed_anchor_dir = ""):
    
    result = {"status": "failed"}
    
    dirname = str(uuid.uuid4())[0:5]
    tname =  dns
    keysize = "rsa:" + str(rsakey)
    completed_user_dir = os.path.join(settings.CA_COMPLETED_DIR, user )
    
    
    subj = '/emailAddress=' + email + \
           '/C='            + country +  \
           '/ST='           + state + \
           '/L='            + city + \
           '/CN='           + common_name + \
           '/O='            + organization 
    
    conf_stub_file_name = tname  + "-crl-stub.cnf"
    conf_stub_file_path = os.path.join(completed_anchor_dir, conf_stub_file_name)
    os.chdir(completed_anchor_dir)
     
    
    #copy over the stub
    copyfile(os.path.join(settings.CA_CONF_DIR,"crl-stub.cnf"),
             os.path.join(completed_anchor_dir, conf_stub_file_name))
    
    
    #get the next serial number
    ##p = open("/opt/ca/conf/serial", "r")
    #serial = str(fp.read())
    #fp.close()
    
    # Modify the stub file --------------------------------------------
    seddns = "s/|DNS|/%s/g" % (dns)
    sedanchordns = "s/|ANCHORDNS|/%s/g" % (anchor_dns)
    #prepare sed strings -----------------
    sedcompletedanchordir = "s#|COMPLETED_ANCHOR_DIR|#%s#g" % (completed_anchor_dir)
    seddays = "s/|DAYS|/%s/g" % (expires)
    sedpublickey = "s#|CERTIFICATE|#%s#g" % (public_key_path)
    sedprivatekey = "s#|PRIVATE_KEY|#%s#g" % (private_key_path)
    sedcountry = "s#|COUNTRY|#%s#g" % (country)
    sedstate= "s#|STATE|#%s#g" % (state)
    sedcity = "s#|CITY|#%s#g" % (city)
    sedcommon_name =  "s#|COMMON_NAME|#%s#g" % (common_name)
    sedorganization = "s#|ORGANIZATION|#%s#g" % (organization)
    sedemail = "s#|EMAIL_ADDRESS|#%s#g" % (email)


    #use sed to modify the file.
    error, output = subprocess.Popen(["sed", "-i", "-e", sedcompletedanchordir,
                                      conf_stub_file_path],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    error, output = subprocess.Popen(["sed", "-i", "-e", seddns,
                                      conf_stub_file_path],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    
    error, output = subprocess.Popen(["sed", "-i", "-e", sedanchordns,
                                      conf_stub_file_path],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()

    
    error, output = subprocess.Popen(["sed", "-i", "-e",
                                      seddays, conf_stub_file_path],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    
    error, output = subprocess.Popen(["sed", "-i", "-e",
                                      sedpublickey, conf_stub_file_path],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    
    error, output = subprocess.Popen(["sed", "-i", "-e",
                                      sedprivatekey, conf_stub_file_path],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()

     
    error, output = subprocess.Popen(["sed", "-i", "-e", sedcountry,
                                      conf_stub_file_path],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    
    error, output = subprocess.Popen(["sed", "-i", "-e", sedstate,
                                      conf_stub_file_path],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()

    error, output = subprocess.Popen(["sed", "-i", "-e", sedcity,
                                      conf_stub_file_path],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()

    error, output = subprocess.Popen(["sed", "-i", "-e", sedcommon_name,
                                      conf_stub_file_path],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    error, output = subprocess.Popen(["sed", "-i", "-e", sedorganization,
                                      conf_stub_file_path],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    
    error, output = subprocess.Popen(["sed", "-i", "-e", sedemail,
                                      conf_stub_file_path],
                                        stdout=subprocess.PIPE,
                                        stderr= subprocess.PIPE
                                        ).communicate()
    

    
    
    
    
    # Get back to the directory we started.
    os.chdir(settings.BASE_DIR) 
    result = {"status": "success"}
    return result
