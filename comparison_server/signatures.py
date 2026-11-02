"""Offline integrity checks only. No trust or revocation claims."""
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from asn1crypto import cms, pem
from pyhanko.sign.validation.generic_cms import validate_sig_integrity
from pyhanko.pdf_utils.reader import PdfFileReader

def verify_cms(raw: bytes, document: bytes):
    base={'trust':'not_checked','revocation':'not_checked','time_trusted':False}
    try:
        if pem.detect(raw): _,_,raw=pem.unarmor(raw)
        info=cms.ContentInfo.load(raw)
        if info['content_type'].native!='signed_data':raise ValueError('not signed data')
        signed=info['content'];certs=[c.chosen for c in signed['certificates'] if c.name=='certificate']
        results=[]
        embedded=signed['encap_content_info']['content'].native
        content=embedded if isinstance(embedded,bytes) else document
        for signer in signed['signer_infos']:
            item=dict(base, mathematical='not_checked',algorithm='unsupported')
            sid=signer['sid']; cert=None
            for c in certs:
                if sid.name=='issuer_and_serial_number' and c.serial_number==sid.chosen['serial_number'].native and c.issuer==sid.chosen['issuer']:
                    cert=c;break
                if sid.name=='subject_key_identifier' and c.key_identifier==sid.chosen.native:
                    cert=c;break
            if cert is None:
                item['message']='Сертификат подписанта не найден.';results.append(item);continue
            now=datetime.now(timezone.utc)
            validity=cert['tbs_certificate']['validity']
            start=validity['not_before'].native;end=validity['not_after'].native
            item.update(subject=cert.subject.human_friendly,issuer=cert.issuer.human_friendly,
                        serial=str(cert.serial_number),fingerprint=hashlib.sha256(cert.dump()).hexdigest(),
                        not_before=start.isoformat(),not_after=end.isoformat(),
                        certificate_time='in_range' if start<=now<=end else 'outside_range')
            digest=signer['digest_algorithm']['algorithm'].native
            algo=signer['signature_algorithm']['algorithm'].native
            item['algorithm_name']=algo+' / '+digest
            if signer['signed_attrs'].native:
                for attr in signer['signed_attrs']:
                    if attr['type'].native=='signing_time':item['claimed_signing_time']=attr['values'][0].native.isoformat()
            if digest not in ('sha256','sha384','sha512') or not any(x in algo for x in ('rsa','ecdsa')):
                item['message']='Алгоритм не поддерживается локальной проверкой.'
            else:
                item['algorithm']='supported'
                try:
                    intact,valid=validate_sig_integrity(signer,cert,signed['encap_content_info']['content_type'].native,hashlib.new(digest,content).digest())
                    item['mathematical']='valid' if intact and valid and (embedded is None or embedded==document) else 'invalid'
                    item['digest_matches']=intact;item['signature_valid']=valid
                except Exception:
                    item['mathematical']='invalid';item['message']='Криптографическая проверка не выполнена успешно.'
            results.append(item)
        return results or [dict(base,mathematical='not_checked',message='В контейнере нет подписантов.')]
    except Exception:
        return [dict(base,mathematical='not_checked',message='Не удалось прочитать контейнер CMS/CAdES.')]

def inspect_signatures(document: Path, uploads: list[Path], fmt: str):
    results=[]
    for index,path in enumerate(uploads,1):
        for item in verify_cms(path.read_bytes(),document.read_bytes()):
            results.append(dict(item,container='detached',index=index))
    if fmt=='pdf':
        try:
            with document.open('rb') as stream:
                reader=PdfFileReader(stream, strict=False)
                for sig in reader.embedded_signatures:
                    sig.compute_integrity_info(skip_diff=True)
                    digest=sig.compute_digest()
                    signed=sig.signed_data
                    # verify_cms expects original content, whereas PDF digests cover ByteRange.
                    cms_bytes=cms.ContentInfo({'content_type':'signed_data','content':signed}).dump()
                    items=verify_cms(cms_bytes,b'')
                    for item,signer in zip(items,signed['signer_infos']):
                        if item.get('algorithm')=='supported':
                            cert=sig.signer_cert
                            intact,valid=validate_sig_integrity(signer,cert,'data',digest)
                            item['mathematical']='valid' if intact and valid else 'invalid'
                        item.update(container='pdf',coverage=str(sig.coverage),
                                    signed_revision=sig.signed_revision,
                                    later_revisions=reader.total_revisions>sig.signed_revision+1)
                        results.append(item)
        except Exception:
            results.append({'container':'pdf','mathematical':'not_checked','inspection_error':True,'message':'Не удалось полностью проверить встроенные подписи PDF.',
                            'trust':'not_checked','revocation':'not_checked'})
    return results
