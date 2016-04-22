#!/usr/bin/env python

from __future__ import print_function
import os
import argparse
import warnings
import numpy as np
from lsst.sims.movingObjects import Orbits
from lsst.sims.movingObjects import ChebyFits

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Generate Chebyshev polynomial coefficients" +
                                     " for a set of orbits, over a given timespan.")
    parser.add_argument("--orbitFile", type=str, default=None,
                        help="File containing the orbits.")
    parser.add_argument("--objStart", type=int, default=None,
                        help="Start coefficient generation at object number 'objStart'. "
                        "Default None - start at 0.")
    parser.add_argument("--objEnd", type=int, default=None,
                        help="End coefficient generation at object number 'objEnd'. "
                        "Default None - finish at last object.")
    parser.add_argument("--nObj", type=int, default=None,
                        help="If specified, then orbitFile is processed and "
                        "written to disk in chunks of 'nObj'.")
    parser.add_argument("--tStart", type=float, default=None,
                        help="Start of timespan to generate coefficients.")
    parser.add_argument("--tEnd", type=float, default=None,
                        help="End of timespan to generate coefficients.")
    parser.add_argument("--tSpan", type=float, default=None,
                        help="Chunk total time into subsets of tSpan (multiple output files)."
                        " If one of tSpan or tEnd is missing, assumes one chunk was meant.")
    parser.add_argument("--skyTol", type=float, default=2.5,
                        help="Sky tolerance for position residuals; default 2.5 mas")
    parser.add_argument("--length", type=float, default=None,
                        help="Chebyshev polynomial length (will self-determine if not given).")
    parser.add_argument("--nDecimal", type=int, default=10,
                        help="Number of decimal places to use for timespan. Default 10.")
    parser.add_argument("--nCoeff", type=int, default=14,
                        help="Number of coefficients to use for the position polynomials. Default 14.")
    args = parser.parse_args()

    # Parse orbit file input values.
    if args.orbitFile is None:
        print("Must specify orbit file to use.")
        exit()

    if not os.path.isfile(args.orbitFile):
        print("Could not find orbit file %s" % (args.orbitFile))
    if args.orbitFile.lower().endswith('s3m'):
        skiprows = 1
    else:
        skiprows = 0

    # Check that basic information about tSpan or tEnd is available.
    if args.tEnd is None and args.tSpan is None:
        print("Must specify at least one of tSpan or tEnd")
        exit()

    # Read orbits.
    orbits = Orbits()
    orbits.readOrbits(args.orbitFile, skiprows=skiprows)

    # Pull out only objStart to objEnd, if either of these is specified.
    if args.objStart is not None or args.objEnd is not None:
        if args.objStart is None:
            args.objStart = 0
        if args.objEnd is None:
            args.objEnd = len(orbits) - 1
        orbits = orbits[args.objStart:args.objEnd + 1]
        fileSuffix = '_obj%d_%d' % (args.objStart, args.objEnd)
    else:
        fileSuffix = ''

    if args.nObj is None:
        nObj = len(orbits)
    else:
        nObj = args.nObj

    # Parse start, end and timespan values (if tStart is None, this depends on epoch in orbit file).
    if args.tStart is None:
        tStart = orbits.orbits.epoch.iloc[0]
        print("tStart was not specified: using the first epoch in the orbits file: %f" % (tStart))
    else:
        tStart = args.tStart

    if args.tSpan is not None and args.tEnd is not None:
        tSpan = args.tSpan
        tEnd = args.tEnd
    elif args.tSpan is not None and args.tEnd is None:
        tSpan = args.tSpan
        tEnd = tStart + tSpan
    elif args.tEnd is None and args.tEnd is not None:
        tEnd = args.tEnd
        tSpan = tEnd - tStart

    timespans = np.arange(tStart, tEnd, tSpan)
    for t in timespans:
        # Set output file names.
        coeffFile = '.'.join(args.orbitFile.split('.')[:-1]) + \
            '_coeffs_%.2f_%.2f' % (t, t + tSpan) + fileSuffix
        residFile = '.'.join(args.orbitFile.split('.')[:-1]) + \
            '_resids_%.2f_%.2f' % (t, t + tSpan) + fileSuffix
        failedFile = '.'.join(args.orbitFile.split('.')[:-1]) + \
            '_failed_%.2f_%.2f' % (t, t + tSpan) + fileSuffix

        # Cycle through nObj at a time, to fit and write data files.
        append = False
        for n in range(0, len(orbits), nObj):
            subset = orbits.orbits[n:n + nObj]
            subsetOrbits = Orbits()
            subsetOrbits.setOrbits(subset)
            # Fit chebyshev polynomials.
            print("Working on objects %d to %d in timespan %f to %f" % (n, n + nObj, t, t + tSpan))
            cheb = ChebyFits(subsetOrbits, t, tSpan, skyTolerance=args.skyTol,
                             nDecimal=args.nDecimal, nCoeff_position=args.nCoeff,
                             ngran=64, nCoeff_vmag=9, nCoeff_delta=5, nCoeff_elongation=6,
                             obscode=807, timeScale='TAI')

            try:
                cheb.calcSegmentLength(length=args.length)
            except ValueError as ve:
                cheb.length = None
                for objId in subsetOrbits.orbits['objId'].as_matrix():
                    cheb.failed.append((objId, tStart, tEnd))
                    warnings.warn('Objid %s to %s (n %d to %d), segment %f to %f - error: %s'
                                  % (subsetOrbits.orbits.objId.iloc[0], subsetOrbits.orbits.objId.iloc[-1],
                                     n, n + nObj, t, t + tSpan, ve.message))

            # Put this in a separate try/except block, because errors here can mask errors in the previous
            # length determination stage otherwise.
            if cheb.length is not None:
                try:
                    cheb.calcSegments()
                except ValueError as ve:
                    for objId in subsetOrbits.orbits['objId'].as_matrix():
                        cheb.failed.append((objId, tStart, tEnd))
                        warnings.warn('Objid %s to %s (n %d to %d), segment %f to %f - error: %s'
                                      % (subsetOrbits.orbits.objId.iloc[0],
                                         subsetOrbits.orbits.objId.iloc[-1],
                                         n, n + nObj, t, t + tSpan, ve.message))

            # Write out coefficients.
            cheb.write(coeffFile, residFile, failedFile, append=append)
            append = True
