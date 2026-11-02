"""Run with LibreOffice's bundled Python; connect to Atlas's private UNO pipe."""
import argparse
import json
import time
from pathlib import Path
import uno
from com.sun.star.beans import PropertyValue


def prop(name,value):
    item=PropertyValue();item.Name=name;item.Value=value;return item


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pipe',required=True)
    parser.add_argument('--input');parser.add_argument('--output');parser.add_argument('--filter')
    parser.add_argument('--wait',type=float,default=60);parser.add_argument('--shutdown',action='store_true')
    parser.add_argument('--probe',action='store_true');parser.add_argument('--keepalive',action='store_true');args=parser.parse_args()
    local=uno.getComponentContext()
    resolver=local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver',local)
    deadline=time.monotonic()+args.wait
    while True:
        try:
            context=resolver.resolve('uno:pipe,name='+args.pipe+';urp;StarOffice.ComponentContext');break
        except Exception:
            if time.monotonic()>=deadline:raise RuntimeError('Конвертер не завершил запуск.')
            time.sleep(.2)
    desktop=context.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop',context)
    if args.probe:print(json.dumps({'ready':True}),flush=True);return
    if args.shutdown:desktop.terminate();return
    if args.keepalive:
        anchor=desktop.loadComponentFromURL('private:factory/swriter','_blank',0,
            (prop('Hidden',True),prop('MacroExecutionMode',0),prop('PickListEntry',False)))
        print(json.dumps({'ready':True}),flush=True)
        try:
            while True:
                desktop.getComponents();time.sleep(2)
        finally:
            try:anchor.close(True)
            except Exception:pass
        return
    document=desktop.loadComponentFromURL(Path(args.input).resolve().as_uri(),'_blank',0,
        (prop('Hidden',True),prop('ReadOnly',True),prop('MacroExecutionMode',0),
         prop('UpdateDocMode',0),prop('PickListEntry',False)))
    if document is None:raise RuntimeError('Не удалось открыть документ конвертером.')
    try:
        document.storeToURL(Path(args.output).resolve().as_uri(),
                            (prop('FilterName',args.filter),prop('Overwrite',True)))
    finally:document.close(True)
    print(json.dumps({'ready':True}))


if __name__=='__main__':main()
