## NOTE : THIS SHIT IS INCOMPLETE AS HELL !


import sys
import argparse


try : 
    import pyvips
    import numpy as np
    HAVE_VIPS = True
except ImportError :
    pyvips = None
    _np = None
    HAVE_VIPS = False


PROGNAME = "tkiv.py"


#===============[Help]==========================
helpText = '''
tkiv.py

Usage : tkiv.py [directory..]
'''

#===============================================


#==============[Parser]=========================
def build_parser() :
    parser = argparse.ArgumentParser(description="tkiv.py")
    parser.add_argument("paths", nargs='*' , default=["."], help="Directories or files to browse")
    parser.add_argument('-h','--help',action='store_true')

    return parser
#===============================================


#================[Main]=========================
def main() :
    parser = build_parser()
    args = parser.parse_args()
    if args.help :
        print(helpText)

    if not HAVE_VIPS and not args.quiet :
        sys.stderr.write(f'''{PROGNAME} : Warning : pyvips is not available.
        Falling back to Pillow instead for image decoding.
                        ''')

    # Collect files
    file_list = []
    if args.from_stdin or (len(args.files == 1) and args.files[0] == '-') :
        sep = '\0' if args.using_null else '\n'
        data = sys.stdin.read()
        for e in data.split(sep):
            if e:
                file_list.append(e)

#===============================================
