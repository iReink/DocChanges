import datetime
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa,ec
from cryptography.hazmat.primitives.serialization import pkcs7
import pytest
from comparison_server.signatures import verify_cms

def signed(data,key,expired=False):
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Atlas Test')])
    now=datetime.datetime.now(datetime.timezone.utc)
    cert=x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(1).not_valid_before(now-datetime.timedelta(days=10)).not_valid_after(now+datetime.timedelta(days=-1 if expired else 1)).sign(key,hashes.SHA256())
    return pkcs7.PKCS7SignatureBuilder().set_data(data).add_signer(cert,key,hashes.SHA256()).sign(serialization.Encoding.DER,[pkcs7.PKCS7Options.DetachedSignature,pkcs7.PKCS7Options.Binary])

@pytest.mark.parametrize('key',[rsa.generate_private_key(public_exponent=65537,key_size=2048),ec.generate_private_key(ec.SECP256R1())])
def test_valid_and_tampered(key):
    signature=signed(b'original',key)
    assert verify_cms(signature,b'original')[0]['mathematical']=='valid'
    assert verify_cms(signature,b'changed')[0]['mathematical']=='invalid'
def test_expired_is_separate():
    signature=signed(b'doc',rsa.generate_private_key(public_exponent=65537,key_size=2048),True)
    result=verify_cms(signature,b'doc')[0]
    assert result['mathematical']=='valid' and result['certificate_time']=='outside_range' and result['trust']=='not_checked'
def test_broken():assert verify_cms(b'not cms',b'original')[0]['mathematical']=='not_checked'

def test_unsupported_algorithm():
    from asn1crypto import cms
    signature=signed(b'doc',rsa.generate_private_key(public_exponent=65537,key_size=2048))
    info=cms.ContentInfo.load(signature)
    info['content']['signer_infos'][0]['signature_algorithm']['algorithm']='1.2.643.7.1.1.3.2'
    item=verify_cms(info.dump(),b'doc')[0]
    assert item['algorithm']=='unsupported' and item['mathematical']=='not_checked'

def test_embedded_pdf_signature(tmp_path):
    from asn1crypto import x509 as ax509,keys
    from pyhanko.sign import signers
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko_certvalidator.registry import SimpleCertificateStore
    from reportlab.pdfgen import canvas
    from comparison_server.signatures import inspect_signatures
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Atlas PDF')]);now=datetime.datetime.now(datetime.timezone.utc)
    cert=x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(2).not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1)).sign(key,hashes.SHA256())
    signer=signers.SimpleSigner(ax509.Certificate.load(cert.public_bytes(serialization.Encoding.DER)),keys.PrivateKeyInfo.load(key.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())),SimpleCertificateStore())
    source=tmp_path/'source.pdf';c=canvas.Canvas(str(source));c.drawString(50,750,'Atlas PDF');c.save()
    output=tmp_path/'signed.pdf'
    with source.open('rb') as inp,output.open('wb') as out:
        signers.sign_pdf(IncrementalPdfFileWriter(inp),signers.PdfSignatureMetadata(field_name='Signature1'),signer=signer,output=out)
    items=inspect_signatures(output,[],'pdf')
    assert items and items[0]['mathematical']=='valid',items
    revised=tmp_path/'revised.pdf'
    from pyhanko.pdf_utils import generic
    with output.open('rb') as inp,revised.open('wb') as out:
        writer=IncrementalPdfFileWriter(inp)
        writer.root[generic.pdf_name('/AtlasTest')]=generic.pdf_string('Later revision')
        writer.update_root();writer.write(out)
    later=inspect_signatures(revised,[],'pdf')
    assert later[0]['mathematical']=='valid' and later[0]['later_revisions'] is True,later

def test_missing_certificate():
    from asn1crypto import cms
    info=cms.ContentInfo.load(signed(b'doc',rsa.generate_private_key(public_exponent=65537,key_size=2048)))
    info['content']['certificates']=[]
    assert verify_cms(info.dump(),b'doc')[0]['mathematical']=='not_checked'
