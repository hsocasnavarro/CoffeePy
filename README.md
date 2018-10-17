# CoffeePy
Automate multitrack podcast editing

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