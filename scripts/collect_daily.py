import os

def enabled(name): return bool(os.getenv(name))

def main():
    print('APIZERO enabled:', enabled('APIZERO_API_KEY'))
    print('ODDS_API enabled:', enabled('ODDS_API_KEY'))
    if not enabled('APIZERO_API_KEY'):
        print('CBA collector is waiting for APIZERO_API_KEY')
if __name__=='__main__': main()
