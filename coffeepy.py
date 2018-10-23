#!/usr/bin/env python3

#
# This code was written to automate some of the Coffee Break podcast
# most basic editing needs. It involves taking a multi-track
# recording, normalizing, compressing (in our own way, designed for
# multi-track recording of conversations), track mixing and de-noising.
#
# Dependencies (modules available with pip): numpy, soundfile
# External programs required (must be in path): sox, lame
#
#
# The code must fulfill the following tasks:
#
# 1) Take one or more input audio files, each file has an audio track
#    with the recording of each microphone. Input files may be passed
#    as arguments (non-interactive mode), otherwise a GUI pops up to
#    interactively select one or more files. Keywords in the config file
#    (~/coffeepy.ini) may also be passed as arguments with the syntax:
#    --keyword=value (example: output_mp3_dir=/tmp). In this case
#    there must be no spaces before or after the = sign and any spaces
#    in the keyword must be replaced with the _ symbol, as in the example.
#    If config options are passed as arguments, then it's considered
#    a temporary behavior and the config file ~/coffeepy.ini is not modified
#
# 2) Optionally, generate a compressed copy of the input files for archival
#    (if "Compress original files" is specified in ~/coffeepy.ini)
#
# 3) For each track file, optimize the audio volume so that all voices are as 
#    loud as possible without distorting (much). In the present implementation, 
#    the optimization is done in the following manner:
#    a) Divide the audio in 1-second bins
#    b) Compute the peak (in absolute value) within each 1-second bin
#    c) Identify continuous blocks of two or more 1-second bins having
#       peak signal above some threshold (here 0.10 times the maximum
#       peak in the entire track). Let's call these blocks "phrases"
#    d) Each phrase is multiplied by a gain so that the phrase peak is
#       at 1. The gain is capped at 2. The gain steps at the beginning
#       and end of each phrase are replaced with a smooth cosine profile
#       transition. The transitions have a 0.1-second duration (proflower
#       and profraise)
#
# 4) Renormalize entire track so that the mean plus 5 times the standard
#    deviation of the peaks of those bins with signal above the threshold
#    is at 0.80. Bins having peak values above 0.85 are compressed
#    according to the following formula: yc=0.85+(y-0.85)/3
#
# 5) Add up all tracks. Compress values exceeding 1.3 according to the
#    following formula: yc=0.8+(y-0.8)/10
#    and those eexceeding 0.85 according to: yc=0.85+(y-0.85)/3
#
# 6) Apply noise reduction to the mixed track using the sox algorithm
#
# 7) Optional: If ffmpeg is available in the system, use its loudnorm
#    filter to perform normalization according to EBU-R128 standard. Set
#    integral loudness to recommended value of -16 (for references see links
#    in comments below). If ffmpeg is not available, skip this step
#
# 7) Write resulting track as wav (optional, if "Output wav dir" is
#    specified in ~/coffeepy.ini) and/or mp3 (optional, if "Output mp3 dir"
#    is specified)
#
# 8) Update configuration file ~/coffeepy.ini with current values to remember
#    them next time, but only if no config options were passed as arguments
#
#
# Requirements
#
# 1) Should be able to work with large files. Input wave files can be
#    up to 4 hours in length with 41000Hz sample rate. Must work on
#    with 8Gb RAM
#
# 2) Should be as fast as possible
#
#
#

import numpy as np
import soundfile as sf
#import matplotlib.pyplot as plt
#from scipy.signal import savgol_filter
import sys
import os.path, shutil
import tkinter as tk
import tkinter.filedialog
import io
import time
from subprocess import Popen, PIPE
import time

# Function to find peaks. Optimized for speed (not readability)
def peaks(datain, step):
    data = np.abs(datain.ravel())
#    data = np.clip(data, None, np.mean(data)+3*np.std(data))
    length = len(data)
    if length % step != 0:
        data=np.append(data,np.zeros(step- (length % step) ))
    length = len(data)
    data.shape = (int(length/step), step)
    max_data = np.maximum.reduce(data,1)
#    min_data = np.minimum.reduce(data,1)
#    return np.concatenate((max_data[:,np.newaxis], min_data[:,np.newaxis]), 1)
    return max_data[:,np.newaxis]

# Function to print both on the terminal and to a file
def printboth(logfile, *args):
    string = ' '.join([str(arg) for arg in args])
    print(string)
    logfile.write(string+'\n')
    logfile.flush()
    return

# Parameters
voicethreshold=0.10 
# To store errors and warnings during processing
errors=[]
# To use with pipes (for sox and lame)
kwargs = {'stdin': PIPE, 'stdout': PIPE, 'stderr': PIPE}

# Set directories and read configuration file
import configparser
from pathlib import Path
try:
    homedir=str(Path.home())
except:
    homedir=os.path.expanduser('~')
import tempfile
tmpdir=tempfile.gettempdir()
rootdir=os.path.abspath(os.sep)
outmp3dir=tmpdir # directory for compressed files
outwavdir=tmpdir # directory for outputfile
compressoriginals='y' # whether or not to save a compressed copy of originals
config=configparser.ConfigParser()
configfile=config.read(os.path.join(homedir,'coffeepy.ini'))
logfilename=os.path.join(tmpdir,'coffeepy.log')
startdir=rootdir

if len(configfile) > 0:
    try:
        startdir=config['Config'].get('Starting dir',startdir)
        tmpdir=config['Config'].get('Temp dir',tmpdir)
        logfilename=config['Config'].get('Logfile',logfilename)
        outmp3dir=config['Config'].get('Output mp3 dir',outmp3dir)
        outwavdir=config['Config'].get('Output wav dir',outwavdir)
        compressoriginals=config['Config'].get('Compress original files',compressoriginals)
        compressoriginals=compressoriginals.lower()
        if compressoriginals != 'y' and compressoriginals != 'n':
            compressoriginals='n'
            errors.append("Unrecognized option in ini file for 'Compress original files'. Assuming 'n'")
    except:
        print('Error in config file. Attempting to read file:'+os.path.join(homedir,'coffeepy.ini'))        

# Open logfile
logfile=open(logfilename,'w')
printboth(logfile,'*** Starting coffeepy at '+time.strftime("%Y-%m-%d %H:%M:%S")+'********')

# Filenames from arguments or pick them up via GUI?
filenames=[]
arguments=[]
if len(sys.argv) > 1:
    for arg in sys.argv[1:]:
        if arg[0:2] == '--':
            arguments.append(arg)
        else:
            filenames.append(arg)

if len(filenames) == 0:
# GUI
    root = tk.Tk()
    root.withdraw()
    filenames = tkinter.filedialog.askopenfilenames(initialdir=startdir,filetypes=[('Audio files','.wav .WAV .ogg .OGG'),('All files','*')])

if len(filenames) == 0:
    printboth(logfile,'Exiting')
    logfile.close()
    sys.exit(0)

if len(arguments) != 0: # arguments override values in config file
    for arg in arguments:
        if 'staring_dir' in arg.lower():
            startdir=arg.split('=')[1]
        if 'temp_dir' in arg.lower():
            tmpdir=arg.split('=')[1]
        if 'logfile' in arg.lower():
            logfilename=arg.split('=')[1]
        if 'output_mp3_dir' in arg.lower():
            outmp3dir=arg.split('=')[1]
        if 'output_wav_dir' in arg.lower():
            outwavdir=arg.split('=')[1]
        if 'compress_original_files' in arg.lower():
            compressoriginals=arg.split('=')[1]

firstfile=True
for filename in filenames:
    extension=os.path.splitext(filename)[1].lower()
    if extension != '.wav' and extension != '.mp3' and extension != '.ogg':
        printboth(logfile, 'Not an audio file. Skpping '+filename)
        continue
    # Save a compressed copy'
    if compressoriginals == 'y':
        if extension == '.mp3' or extension == '.ogg': # just copy it
            filenamesplit=os.path.basename(filename)
            outfilename=os.path.join(outmp3dir,filenamesplit)
            if os.path.normcase(os.path.normpath(os.path.realpath(filename))) != \
               os.path.normcase(os.path.normpath(os.path.realpath(outfilename))):           
                printboth(logfile,'Copying '+outfilename)
                shutil.copyfile(filename,outfilename)
        else: # Compress
            outfile=os.path.basename(filename)
            outfile=os.path.splitext(outfile)[0]+'.mp3'
            outfile=os.path.join(outmp3dir,outfile)
            printboth(logfile,'Compressing '+outfile)
# First use of virtual file (others below). Create BytesIO buffer
            wavbuffer=io.BytesIO()
            sf.write(wavbuffer,data,samplerate,format='wav')
            pipe = Popen(['lame','--preset','fast','standard','-',outfile], **kwargs)
            (output,err)=pipe.communicate(input=wavbuffer.getvalue())
            wavbuffer.close()

    # Read file
    if extension == '.mp3':
        printboth(logfile,'Error reading '+filename)
        printboth(logfile,'Input files in mp3 format not supported. Skipping it')
        continue
        
    printboth(logfile,'reading '+filename)
    with open(filename,'rb') as f:
        data, samplerate = sf.read(f)
    printboth(logfile,'ok')
    # Process data
    data=data/np.max(data)
    length=len(data)
    if firstfile: # Store values to make sure all files are consistent
        firstfile=False
        dataout=np.zeros(length)
        noiseout=np.zeros(samplerate)
        samplerate0=samplerate
        length0=length
    else:
        if samplerate != samplerate0:
            printboth(logfile,'Filename has a different samplerate ({} instead of {})'.format(samplerate,samplerate0))
            logfile.close()
            sys.exit(1)
        if length != length0:
            printboth(logfile,'Filename has a different duration ({} samples instead of {})'.format(length,length0))
            logfile.close()
            sys.exit(1)

    # Take 1-second bins to find peaks, determine if voice or silence
    pk=peaks(data,samplerate) # peaks in 1-second bins
    printboth(logfile,'peaks found')
    maxpk=np.max(pk)
    indvoice=[i for i in range(len(pk)) if pk[i] > voicethreshold*maxpk]
    printboth(logfile,'indvoice computed')
    voice=np.zeros(len(pk))
    voice[indvoice]=1
    printboth(logfile,'voice computed')
    # Take a noise sample from this track
    imin=np.argmin(pk) # Find minimum
    iminhours=int(imin/samplerate/3600)
    iminmin=int((imin/samplerate-iminhours*3600)/60)
    iminsec=int((imin/samplerate-iminhours*3600-iminmin*60))
    printboth(logfile,'  taking noise from silence at {}hours, {}mins, {}seconds'.format(iminhours,iminmin,iminsec))
    noise=data[imin*samplerate:(imin+1)*samplerate]

    # Define profile of volume raising and lowering
    lengthprof=int(samplerate/10)
    if lengthprof < 100:
        printboth(logfile,'Error, too few samples')
        logfile.close()
        sys.exit(1)
    proflower=0.5*(1+np.cos(np.arange(lengthprof)/lengthprof*np.pi))
    profraise=0.5*(1-np.cos(np.arange(lengthprof)/lengthprof*np.pi))

    # Create gain profile
    length2=len(voice)
    gain=np.ones(length)
    i0=1
    i1=i0
    end=False
    while not end:
        while not (voice[i0]==0 and voice[i0+1]==1) and i0 < length2-3:
            i0=i0+1
        if i0 > length2-4:
            end=True
            break
        i1=i0+1
        while not (voice[i1]==1 and voice[i1+1]==0) and i1 < length2-2:
            i1=i1+1
        if i1 > length2-3:
            end=True
            break
        if voice[i0] == 1 and voice[i0+1] == 1: # If phrase is at least length 2-seconds
            idx0=i0*samplerate
            idx1=i1*samplerate+1
            gain[idx0:idx1]=min(1./max(pk[i0+1:i1+1]),2) # gain is capped to 2
            step=gain[idx0]-gain[idx0-1]
            gain[idx0-lengthprof:idx0]=gain[idx0-1]+step*profraise
            if idx1+lengthprof+1 < length:
                step=gain[idx1-1]-gain[idx1+2]
                gain[idx1:idx1+lengthprof]=gain[idx1+1]+step*proflower
        i0=i1+1
    printboth(logfile,'gain computed')
    
    # Apply gain
    data=np.multiply(data,gain)

    # Silence bins with no signal or pops (pops are noises shorter than 0.1sec)
    printboth(logfile,'muting silence and removing pops')
    absdata=np.abs(data)
    imin=np.argmin(pk) # bin with minimum signal. Assume this is noise
    noiselev=np.std(absdata[imin*samplerate:(imin+1)*samplerate])
    for i0 in range(length2):
        bin=absdata[i0*samplerate:(i0+1)*samplerate]
        if np.sum(bin > 5*noiselev)/samplerate < 0.1: # if no signal longer
            data[i0*samplerate:(i0+1)*samplerate]=0.
    
    printboth(logfile,'renormalizing track')
    # Normalize with distortion above 5-sigma
    absdata=np.abs(data)
    absdata=absdata[absdata > 0.1] # consider frames with signal only
    if len(absdata) > 0:
        norm=np.mean(absdata)+np.std(absdata)*5
    else:
        norm=1.
    data=data/norm*.8
    # For Coffee Break only
    # Trick for teleconference track (always sounds louder, for some reason)
    #if '_L.' in filename:
    #    printboth(logfile,'Trick for reducing volume in telecon track')
    #    data=data*.8
    #

    # Look for saturations in mixed track
    data=np.where(data > .85, .85+(data-.85)/3,data)
    data=np.where(data < -.85, -.85+(data+.85)/3,data)
    dataout=dataout+np.clip(data,-1.,1.)
    # Add noise from this track to global noise
    noiseout=noiseout+noise

if firstfile: # No valid files have been found
    printboth(logfile,'No valid files found. Exiting at '+time.strftime("%Y-%m-%d %H:%M:%S"))
    logfile.close()
    
if len(filenames) >= 2:
    printboth(logfile,'renormalizing mix')
    # Look for saturations in mixed track
    dataout=np.where(dataout > 1.3, .8+(dataout-.8)/10,dataout)
    dataout=np.where(dataout < -1.3, -.8+(dataout+.8)/10,dataout)
    dataout=np.where(dataout > .85, .85+(dataout-.85)/3,dataout)
    dataout=np.where(dataout < -.85, -.85+(dataout+.85)/3,dataout)
    dataout=np.clip(dataout,-1.,1.)
#
# de-noise
# according to https://stackoverflow.com/questions/44159621/how-to-denoise-with-sox
printboth(logfile,'Noise reduction')
wavbuffer=io.BytesIO()
sf.write(wavbuffer,noiseout,samplerate,format='wav')

# Use sox to denoise. We pipe BytesIO buffer through sox
# First, create noise profile noise.prof. Create sox pipe
pipe = Popen(['sox','-','-n','noiseprof',os.path.join(tmpdir,'noise.prof')], **kwargs)
noisebuffer=wavbuffer.getvalue()
pipe.communicate(input=noisebuffer) # Send noise data to sox
# Now filter the rest using noise.prof. Create sox pipe
pipe = Popen(['sox','-','-t','wav','-','noisered',os.path.join(tmpdir,'noise.prof'),'0.21'], **kwargs)
wavbuffer.close()
wavbuffer=io.BytesIO()
sf.write(wavbuffer,dataout,samplerate,format='wav')
(output,err)=pipe.communicate(input=wavbuffer.getvalue())
wavbuffer.close()
wavbuffer=io.BytesIO(output)
dataout,samplerate=sf.read(wavbuffer)
wavbuffer.close()

# EBU-R128 Normalization. Use loudnorm algorithm to set loudness to recommended -16 value
# https://theaudacitytopodcast.com/why-and-how-your-podcast-needs-loudness-normalization-tap307/
# http://k.ylo.ph/2016/04/04/loudnorm.html
# Is ffmpeg available?
try:
    pipe = Popen(['ffmpeg'], **kwargs)
    haveffmpeg=True # Yes. Use ffmpeg loudnorm filter
except:
    haveffmpeg=False # No. Do nothing
    printboth(logfile,'ffmpeg is not available. loudnorm normalization will not be done')

if haveffmpeg:
    printboth(logfile,'Setting LUFS loudness to recommended value -16')
    wavbuffer=io.BytesIO()
    sf.write(wavbuffer,dataout,samplerate,format='wav')
    # pipe = Popen(['ffmpeg','-i','pipe:0','-f','wav','pipe:1'], **kwargs)
    pipe = Popen(['ffmpeg','-i','pipe:0','-af','loudnorm=print_format=json','-f','null','pipe:1'], **kwargs)
    (output,err)=pipe.communicate(input=wavbuffer.getvalue())
    lines=err.decode().split('\n')
    for line in lines:
        if "input_i" in line:
            measI=(line.split('"')[3])
        if "input_tp" in line:
            measTP=(line.split('"')[3])
        if "input_lra" in line:
            measLRA=(line.split('"')[3])
        if "input_thresh" in line:
            measThres=(line.split('"')[3])
        if "target_offset" in line:
            measOffset=(line.split('"')[3])
    printboth(logfile,'   Measured I:{}, TP:{}, LRA:{}, Threshold:{}, Offset:{}'.format(measI,measTP,measLRA,measThres,measOffset))
    printboth(logfile,'Renormalizing')
    loudnormstr='loudnorm=I=-16:TP=-1.5:LRA=11:measured_I='+measI+':measured_LRA='+measLRA+':measured_TP='+measTP+':measured_thresh='+measThres+':offset='+measOffset+':linear=true:print_format=none'
#ffmpeg -i in.wav -af loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=-27.61:measured_LRA=18.06:measured_TP=-4.47:measured_thresh=-39.20:offset=0.58:linear=true:print_format=summary -ar 48k out.wav
    pipe = Popen(['ffmpeg','-i','pipe:0','-af',loudnormstr,'-f','wav','-ar',str(samplerate),'pipe:1'], **kwargs)
    (output,err)=pipe.communicate(input=wavbuffer.getvalue())
    wavbuffer.close()
    wavbuffer=io.BytesIO(output)
    dataout,samplerate=sf.read(wavbuffer)
    
# All finished
# Write output file
if outwavdir != '':
    outfile=os.path.join(outwavdir,'compressed.wav')
    if len(filenames) >= 2:
        outfile=os.path.join(outwavdir,'mix.wav')
    printboth(logfile,'writing...')
    sf.write(outfile,dataout,samplerate)

if outmp3dir != '':
    outfile=os.path.join(outmp3dir,'compressed.mp3')
    if len(filenames) >= 2:
        outfile=os.path.join(outmp3dir,'mix.mp3')
    print ('Compressing output file '+outfile)
    wavbuffer=io.BytesIO()
    sf.write(wavbuffer,dataout,samplerate,format='wav')
    pipe = Popen(['lame','--preset','fast','standard','-',outfile], **kwargs)
    (output,err)=pipe.communicate(input=wavbuffer.getvalue())
    wavbuffer.close()

# Write config file with current settings, but only if no arguments
# have been used
if len(arguments) == 0:
    startdir=os.path.dirname(filename)
    config['Config'] = {'Starting dir': startdir,
                        'Temp dir':tmpdir,
                        'Output mp3 dir':outmp3dir ,
                        'Output wav dir':outwavdir ,
                        'Compress original files':compressoriginals,
                        'Logfile':logfilename }
    with open(os.path.join(homedir,'coffeepy.ini'), 'w') as configfile:
        config.write(configfile)
        
# Print errors
if len(errors) > 0:
    printboth(logfile,'\n\n  !!!!!!!!!!!!!! Error(s) found during processing !!!!!!!!! ')
    for error in errors:
        printboth(logfile,error)
    printboth('Exiting at '+time.strftime("%Y-%m-%d %H:%M:%S"))
    logfile.close()
else:
     printboth(logfile,'Finished \nNormal exit at '+time.strftime("%Y-%m-%d %H:%M:%S"))
     logfile.close()
        


