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
#    with the recording of each microphone
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
# 7) Write resulting track as wav (optional, if "Output wav dir" is
#    specified in ~/coffeepy.ini) and/or mp3 (optional, if "Output mp3 dir"
#    is specified)
#
# 8) Update configuration file ~/coffeepy.ini with current values to remember
#    them next time
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
from subprocess import Popen, PIPE

# Routine to find peaks. Optimized for speed (not readability)
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

# Parameters
voicethreshold=0.10 
# To store errors and warnings during processing
errors=[]
# To use with pipes (for sox and lame)
kwargs = {'stdin': PIPE, 'stdout': PIPE, 'stderr': PIPE}

# Set directories and read configuration file
import configparser
from pathlib import Path
homedir=str(Path.home())
import tempfile
tmpdir=tempfile.gettempdir()
rootdir=os.path.abspath(os.sep)
outmp3dir=tmpdir # directory for compressed files
outwavdir=tmpdir # directory for outputfile
compressoriginals='y' # whether or not to save a compressed copy of originals
config=configparser.ConfigParser()
configfile=config.read(os.path.join(homedir,'coffeepy.ini'))
startdir=rootdir

if len(configfile) > 0:
    try:
        startdir=config['Config'].get('Starting dir',startdir)
        tmpdir=config['Config'].get('Temp dir',tmpdir)
        outmp3dir=config['Config'].get('Output mp3 dir',outmp3dir)
        outwavdir=config['Config'].get('Output wav dir',outwavdir)
        compressoriginals=config['Config'].get('Compress original files (y/n)',compressoriginals)
        compressoriginals=compressoriginals.lower()
        if compressoriginals != 'y' and compressoriginals != 'n':
            compressoriginals='n'
            errors.append("Unrecognized option in ini file for 'Compress original files'. Assuming 'n'")
    except:
        print('Error in config file. Attempting to read file:'+os.path.join(homedir,'coffeepy.ini'))        

# GUI
root = tk.Tk()
root.withdraw()
filenames = tkinter.filedialog.askopenfilenames(initialdir=startdir,filetypes=[('Audio files','.wav .WAV .ogg .OGG .mp3 .MP3'),('All files','*')])

if len(filenames) == 0:
    print('Exiting')
    sys.exit(0)

firstfile=True
for filename in filenames:
    # Read file
    print('reading '+filename)
    with open(filename,'rb') as f:
        data, samplerate = sf.read(f)
    print('ok')
    # Save a compressed copy'
    if compressoriginals == 'y':
        extension=os.path.splitext(filename)[1].lower()
        if extension == '.mp3' or extension == '.ogg': # just copy it
            filenamesplit=os.path.basename(filename)
            outfilename=os.path.join(outmp3dir,filenamesplit)
            if os.path.normcase(os.path.normpath(os.path.realpath(filename))) != \
               os.path.normcase(os.path.normpath(os.path.realpath(outfilename))):           
                print('Copying '+outfilename)
                shutil.copyfile(filename,outfilename)
        else: # Compress
            outfile=os.path.splitext(filename)[0]+'.mp3'
            print('Compressing '+outfile)
            outfile=os.path.join(outmp3path,outfile)
# First use of virtual file (others below). Create BytesIO buffer
            wavbuffer=io.BytesIO()
            sf.write(wavbuffer,data,samplerate,format='wav')
            pipe = Popen(['lame','--preset','fast','standard','-',outfile], **kwargs)
            (output,err)=pipe.communicate(input=wavbuffer.getvalue())
            wavbuffer.close()

    # Process data
    data=data/np.max(data)
    length=len(data)
    if firstfile: # Store values to make sure all files are consistent
        firstfile=False
        dataout=np.zeros(length)
        samplerate0=samplerate
        length0=length
    else:
        if samplerate != samplerate0:
            print('Filename has a different samplerate ({} instead of {})'.format(samplerate,samplerate0))
        if length != length0:
            print('Filename has a different duration ({} samples instead of {})'.format(length,length0))

    # Take 1-second bins to find peaks, determine if voice or silence
    pk=peaks(data,samplerate) # peaks in 1-second bins
    print('peaks found')
    maxpk=np.max(pk)
    indvoice=[i for i in range(len(pk)) if pk[i] > voicethreshold*maxpk]
    print('indvoice computed')
    voice=np.zeros(len(pk))
    voice[indvoice]=1
    print('voice computed')

    # Define profile of volume raising and lowering
    lengthprof=int(samplerate/10)
    if lengthprof < 100:
        print('Error, too few samples')
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
    print('gain computed')

    # Apply gain
    data=np.multiply(data,gain)

    print('renormalizing track')
    # Normalize with distortion above 5-sigma
    absdata=np.abs(data)
    absdata=absdata[absdata > 0.1] # consider frames with signal only
    norm=np.mean(absdata)+np.std(absdata)*5
    data=data/norm*.8
    # Trick for teleconference track (always sounds louder)
    if '_L.' in filename:
        print('Trick for reducing volume in telecon track')
        data=data*.8
    #
    # Look for saturations in mixed track
    data=np.where(data > .85, .85+(data-.85)/3,data)
    data=np.where(data < -.85, -.85+(data+.85)/3,data)
    dataout=dataout+np.clip(data,-1.,1.)

if len(filenames) >= 2:
    print('renormalizing mix')
    # Look for saturations in mixed track
    dataout=np.where(dataout > 1.3, .8+(dataout-.8)/10,dataout)
    dataout=np.where(dataout < -1.3, -.8+(dataout+.8)/10,dataout)
    dataout=np.where(dataout > .85, .85+(dataout-.85)/3,dataout)
    dataout=np.where(dataout < -.85, -.85+(dataout+.85)/3,dataout)
    dataout=np.clip(dataout,-1.,1.)
#

# de-noise
# according to https://stackoverflow.com/questions/44159621/how-to-denoise-with-sox
print('Noise reduction')

wavbuffer=io.BytesIO()
sf.write(wavbuffer,dataout,samplerate,format='wav')

# Use sox to denoise. We pipe BytesIO buffer through sox
# First, create noise profile noise.prof. Create sox pipe
pipe = Popen(['sox','-','-n','noiseprof',os.path.join(tmpdir,'noise.prof')], **kwargs)
noisebuffer=wavbuffer.getvalue()[0:samplerate*2] # 2-seconds
if np.sum(voice[0:2]) != 0:
    print("\nError! De-noise requires 2-seconds of silence at beginning of track")
    print("Apparently that's not the case here")
    print("Skipping noise reduction\n")
    errors.append('Could not apply noise reduction')
    wavbuffer.close()
else:
    pipe.communicate(input=noisebuffer) # Send noise data to sox
    # Now filter the rest using noise.prof. Create sox pipe
    pipe = Popen(['sox','-','-t','wav','-','noisered',os.path.join(tmpdir,'noise.prof'),'0.21'], **kwargs)
    (output,err)=pipe.communicate(input=wavbuffer.getvalue())
    wavbuffer.close()
    wavbuffer=io.BytesIO(output)
    dataout,samplerate=sf.read(wavbuffer)
wavbuffer.close()

# Write output file
if outwavdir != '':
    outfile=os.path.join(outwavdir,'compressed.wav')
    if len(filenames) >= 2:
        outfile=os.path.join(outwavdir,'mix.wav')
    print('writing...')
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

# Write config file with current settings
startdir=os.path.dirname(filename)
config['Config'] = {'Starting dir': startdir,
                    'Temp dir':tmpdir,
                    'Output mp3 dir':outmp3dir ,
                    'Output wav dir':outwavdir ,
                    'Compress original files (y/n)':compressoriginals}
with open(os.path.join(homedir,'coffeepy.ini'), 'w') as configfile:
    config.write(configfile)
        
# Print errors
if len(errors) > 0:
    print('\n\n  !!!!!!!!!!!!!! Error(s) found during processing !!!!!!!!! ')
    for error in errors:
        print(error)
else:
     print('Finished \nNormal exit')   



