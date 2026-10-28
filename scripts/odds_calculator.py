from typing import Tuple

def hk_to_decimal(v:float)->float: return v+1
def american_to_decimal(v:float)->float: return 1+v/100 if v>0 else 1+100/abs(v)
def no_vig(a:float,b:float)->Tuple[float,float,float]:
    if a<=1 or b<=1: raise ValueError('decimal odds must be > 1')
    ra,rb=1/a,1/b; hold=ra+rb-1
    return ra/(ra+rb),rb/(ra+rb),hold
