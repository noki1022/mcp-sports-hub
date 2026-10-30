#!/usr/bin/env python3
"""Read only 007 JC's publicly available JS to audit market-side orientation.

No bookmaker prices are used to assume lottery field orientation. Does not
request any discovered endpoints, does not access blocked CP lottery pages.
"""
import json,re
from probe_007_jc_scripts import ORIGIN,UA,get_bytes,robots_policy

TARGETS=["_glJC.jcOddsLq = function","getOddsListByType","var homeWin =","var guestWin =","getOddsListByType()","jcCID ="]
MAX_SNIPPETS=4

def inspect(raw):
    source=raw.decode("utf-8-sig","replace")
    result={}
    for token in TARGETS:
        snippets=[]
        for m in list(re.finditer(re.escape(token),source,re.I))[:MAX_SNIPPETS]:
            part=source[max(0,m.start()-160):m.end()+1400]
            part=re.sub(r"\s+"," ",part)
            snippets.append(part[:1560])
        result[token]=snippets
    return result
def audit():
    rp,status=robots_policy()
    if rp is False:raise RuntimeError("ROBOTS_CHECK_UNAVAILABLE_"+status)
    outputs={}
    for path in ("/js/basket.js","/js/common.js"):
        if rp is not None and not rp.can_fetch(UA,ORIGIN+path):
            outputs[path]={"status":"ACCESS_DISALLOWED"}
            continue
        outputs[path]={"status":"READ_OK","callsite":inspect(get_bytes(ORIGIN+path,240000))}
    return outputs
def self_test():
    x=inspect(b"var homeWin = y; _glJC.jcOddsLq = function (v) {return v;};")
    assert x["var homeWin ="] and x["_glJC.jcOddsLq = function"]
    print("JC_ORIENTATION_READ_ONLY_UNIT_TEST_PASS")
if __name__=="__main__":
    import sys
    if "--self-test" in sys.argv:self_test()
    else:print("JC_LOTTERY_SIDE_SOURCE_CALLSITES",json.dumps(audit(),ensure_ascii=False))
