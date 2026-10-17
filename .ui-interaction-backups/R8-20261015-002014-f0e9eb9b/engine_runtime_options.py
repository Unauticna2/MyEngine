"""Developer-owned runtime controls; editor navigation is independent."""
DEFAULTS={'diagnosticTitle':False,'cameraReset':False,'scriptReload':False,'wKeys':False,
          'lightKeys':False,'escapeQuits':False,'freeFly':True,'mouseLook':True}
def normalized(value=None):
    result=dict(DEFAULTS)
    for k,v in (value or {}).items():
        if k not in result:raise ValueError('Unknown runtime option: '+k)
        if type(v) is not bool:raise ValueError(k+' must be true/false')
        result[k]=v
    return result

def native_flags(options,editor=False):
    if editor:return 15
    return (1 if options['mouseLook'] else 0)|(2 if options['cameraReset'] else 0)|(4 if options['escapeQuits'] else 0)|(8 if options['freeFly'] else 0)
