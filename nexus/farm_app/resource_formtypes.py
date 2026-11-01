"""Shared declarative resource form helpers."""
def f(key,label,kind='text',required=True,**extra):return dict(key=key,label=label,type=kind,required=required,**extra)
def choice(key,label,options):return f(key,label,'select',options=options)
def spec(title,purpose,effect,fields):return dict(title=title,purpose=purpose,effect=effect,fields=fields)
