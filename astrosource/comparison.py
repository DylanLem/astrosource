import glob
import sys
import os
from pathlib import Path
from collections import namedtuple
import numpy as np

from numpy import min, max, median, std, isnan, delete, genfromtxt, savetxt, load, \
    asarray, add, append, log10, average, array, where
from astropy.units import degree, arcsecond
from astropy.coordinates import SkyCoord
from astroquery.sdss import SDSS
from astroquery.vo_conesearch import ConeSearch
from astroquery.vo_conesearch.exceptions import VOSError
from astroquery.vizier import Vizier


from astrosource.utils import AstrosourceException

import logging

logger = logging.getLogger('astrosource')


def find_comparisons(targets, parentPath=None, fileList=None, photlist=[], stdMultiplier=2.5, thresholdCounts=10000000, variabilityMultiplier=2.5, removeTargets=True, acceptDistance=1.0):
    '''
    Find stable comparison stars for the target photometry

    Parameters
    ----------
    parentPath : str or Path object
            Path to the data files
    stdMultiplier : int
            Number of standard deviations above the mean to cut off the top. The cycle will continue until there are no stars this many std.dev above the mean
    thresholdCounts : int
            Target countrate for the ensemble comparison. The lowest variability stars will be added until this countrate is reached.
    variabilityMax : float
            This will stop adding ensemble comparisons if it starts using stars higher than this variability
    removeTargets : int
            Set this to 1 to remove targets from consideration for comparison stars
    acceptDistance : float
            Furthest distance in arcseconds for matches

    Returns
    -------
    outfile : str

    '''
    sys.stdout.write("⭐️ Find stable comparison stars for differential photometry\n")
    sys.stdout.flush()
    # Get list of phot files
    if not parentPath:
        parentPath = Path(os.getcwd())
    if type(parentPath) == 'str':
        parentPath = Path(parentPath)

    comparisons = remove_stars_targets(photlist, acceptDistance, targets, removeTargets)

    # Add up all of the counts of all of the comparison stars
    # To create a gigantic comparison star.
    logger.debug("Please wait... calculating ensemble comparison star for each image")

    fileCount = np.ndarray.sum(comparisons, axis=1)[:,4]
    logger.debug("Total total {}".format(np.sum(np.array(fileCount))))
    starRejecter = [True for i in range(comparisons.shape[1])]
    oldrejects = [False for i in range(comparisons.shape[1])]
    while True:

        # Calculate the variation in each candidate comparison star in brightness
        # compared to this gigantic comparison star.
        numfiles = comparisons[0].size
        stdCompStar, sortStars = calculate_comparison_variation(comparisons, fileCount)

        variabilityMax=(min(stdCompStar)*variabilityMultiplier)
        logger.critical(stdCompStar)
        logger.critical(variabilityMax)

        # Calculate and present the sample statistics
        stdCompMed = median(stdCompStar)
        stdCompStd = std(stdCompStar)

        logger.debug(f"Median of comparisons = {stdCompMed}")
        logger.debug(f"STD of comparisons = {stdCompStd}")

        # Delete comparisons that have too high a variability
        if min(stdCompStar) > 0.002:
            for j, stdComp in enumerate(stdCompStar):
                #logger.debug(stdCompStar[j])
                if stdComp > (stdCompMed + (stdMultiplier*stdCompStd)) or isnan(stdComp):
                    logger.debug(f"Star {j} Rejected, Variability too high")
                    starRejecter[j] = False
                sys.stdout.write('.')
                sys.stdout.flush()
            if sum(starRejecter) != len(starRejecter) :
                logger.warning("Rejected {} stars".format(len(starRejecter)-sum(starRejecter)))
        else:
            logger.info("Minimum variability is too low for comparison star rejection by variability.")


        comparisons = array([c[starRejecter] for c in comparisons])

        # Calculate and present statistics of sample of candidate comparison stars.
        logger.info("Median variability {:.6f}".format(median(stdCompStar)))
        logger.info("Std variability {:.6f}".format(std(stdCompStar)))
        logger.info("Min variability {:.6f}".format(min(stdCompStar)))
        logger.info("Max variability {:.6f}".format(max(stdCompStar)))
        logger.info("Number of Stable Comparison Candidates {}".format(comparisons.shape[1]))
        # Once we have stopped rejecting stars, this is our final candidate catalogue then we start to select the subset of this final catalogue that we actually use.
        if starRejecter == oldrejects :
            break
        else:
            logger.warning("Trying again")
            sys.stdout.write('💫')
            sys.stdout.flush()
            oldrejects[:] = starRejecter

    sys.stdout.write('\n')
    logger.info('Statistical stability reached.')
    # Sort through and find the largest file and use that as the reference file
    outfile, num_comparisons = final_candidate_catalogue(parentPath, comparisons, sortStars, thresholdCounts, variabilityMax)
    return outfile, num_comparisons

def final_candidate_catalogue(parentPath, comparisons, sortStars, thresholdCounts, variabilityMax):

    logger.info('List of stable comparison candidates output to stdComps.csv')

    savetxt(parentPath / "stdComps.csv", sortStars, delimiter=",", fmt='%0.8f')

    # The following process selects the subset of the candidates that we will use (the least variable comparisons that hopefully get the request countrate)

    referenceFrame = comparisons[0]
    fileRaDec = SkyCoord(ra=referenceFrame[:,0]*degree, dec=referenceFrame[:,1]*degree, frame='icrs', unit=degree)

    # SORT THE COMP CANDIDATE FILE such that least variable comparison is first

    sortorder=sortStars[:,2].argsort()
    if sortStars.size == 13 and sortStars.shape[0] == 1:
        sortStars = [sortStars]
    logger.info(sortorder)

    # PICK COMPS UNTIL OVER THE THRESHOLD OF COUNTS OR VARIABILITY ACCORDING TO REFERENCE IMAGE
    logger.debug("PICK COMPARISONS UNTIL OVER THE THRESHOLD ACCORDING TO REFERENCE IMAGE")
    compFile=[]
    tempCountCounter=0.0
    finalCountCounter=0.0
    for j in sortorder:
        matchCoord=SkyCoord(ra=sortStars[j][0]*degree, dec=sortStars[j][1]*degree)
        idx, d2d, d3d = matchCoord.match_to_catalog_sky(fileRaDec)
        logger.info(f"{sortStars[j][2]} {variabilityMax}")
        if tempCountCounter < thresholdCounts:
            if len(sortorder) == 1 or sortStars[j][2] < variabilityMax:
                compFile.append([sortStars[j][0],sortStars[j][1],sortStars[j][2]])
                logger.debug("Comp " + str(j+1) + " std: " + str(sortStars[j][2]))
                logger.debug("Cumulative Counts thus far: " + str(tempCountCounter))
                finalCountCounter=add(finalCountCounter,referenceFrame[idx][4])
                logger.info(f"{idx} {j}")

        tempCountCounter=add(tempCountCounter,referenceFrame[idx][4])

    logger.debug("Selected stars listed below:")
    logger.debug(compFile)

    logger.info("Finale Ensemble Counts: " + str(finalCountCounter))
    compFile=asarray(compFile)

    logger.info(str(compFile.shape[0]) + " Stable Comparison Candidates below variability threshold output to compsUsed.csv")

    outfile = parentPath / "compsUsed.csv"
    savetxt(outfile, compFile, delimiter=",", fmt='%0.8f')
    return outfile, compFile.shape[0]

def calculate_comparison_variation(comparisons, fileCount):
    stdCompStar=[]
    sortStars=[]
    numfiles, numstars, el = asarray(comparisons).shape

    for j in range(numstars):
        compDiffMags = []
        logger.debug("*************************")
        logger.debug(f"RA : {comparisons[0][j][0]}")
        logger.debug(f"DEC: {comparisons[0][j][1]}")
        for q, count in enumerate(fileCount):
            calc = 2.5 * log10(comparisons[q][j][4]/count)
            compDiffMags = append(compDiffMags,calc)
            logger.critical(comparisons[q][j])
            logger.critical(count)

        logger.debug("VAR: " +str(std(compDiffMags)))
        if std(compDiffMags) == np.nan:
            sys.exit()
        stdCompStar.append(std(compDiffMags))
        sortStars.append([comparisons[0][j][0], comparisons[0][j][1],std(compDiffMags),0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0])
    return stdCompStar, array(sortStars)

def remove_stars_targets(photlist, acceptDistance, targetFile, removeTargets):
    max_sep=acceptDistance * arcsecond
    logger.info("Removing Variable Stars from potential Comparisons")

    compFile = photlist[0]
    fileRaDec = SkyCoord(ra=compFile[:,0]*degree, dec=compFile[:,1]*degree)

    # Remove any nan rows from targetFile
    targetRejecter=[]
    if not (targetFile.shape[0] == 4 and targetFile.size ==4):
        for z in range(targetFile.shape[0]):
          if isnan(targetFile[z][0]):
            targetRejecter.append(z)
        targetFile=delete(targetFile, targetRejecter, axis=0)

    # Get Average RA and Dec from file
    logger.debug(average(compFile[:,0]))
    logger.debug(average(compFile[:,1]))
    avgCoord=SkyCoord(ra=(average(compFile[:,0]))*degree, dec=(average(compFile[:,1]))*degree)
    # Check VSX for any known variable stars and remove them from the list
    variableResult=Vizier.query_region(avgCoord, '0.33 deg', catalog='VSX')['B/vsx/vsx']

    logger.debug(variableResult)
    logger.debug(variableResult.keys())

    raCat=array(variableResult['RAJ2000'].data)
    logger.debug(raCat)
    decCat=array(variableResult['DEJ2000'].data)
    logger.debug(decCat)
    mask = [True for i in range(0,compFile.shape[0])]
    for t in range(raCat.size):

        compCoord=SkyCoord(ra=raCat[t]*degree, dec=decCat[t]*degree)

        if not (compFile.shape[0] == 2 and compFile.size == 2):
            catCoords=SkyCoord(ra=compFile[:,0]*degree, dec=compFile[:,1]*degree)
            idxcomp,d2dcomp,d3dcomp=compCoord.match_to_catalog_sky(catCoords)
        elif not (raCat.shape[0] == 1 and raCat.size == 1): ### this is effictively the same as below
            catCoords=SkyCoord(ra=compFile[0]*degree, dec=compFile[1]*degree)
            try:
                idxcomp,d2dcomp,d3dcomp=compCoord.match_to_catalog_sky(catCoords)
            except ValueError as e:
                logger.critical(e)
                logger.critical(compCoord)
                logger.critical(catCoords)
                raise AstrosourceException("Error with variable star catalogue match")
        else:
            if abs(compFile[0]-raCat[0]) > 0.0014 and abs(compFile[1]-decCat[0]) > 0.0014:
                d2dcomp = 9999

        logger.debug(d2dcomp)
        if d2dcomp != 9999:
            if d2dcomp.arcsecond.any() < max_sep.value:
                logger.debug("Variable star match!")
                varStarReject.append(t)
                mask[idxcomp] = False
            else:
                logger.debug("No Variable star match!")

    logger.debug("Number of stars prior to VSX reject")
    logger.debug(photlist)
    logger.debug(photlist[0].shape[0])
    photlist = [c[mask] for c in photlist]
    logger.debug("Number of stars post to VSX reject")
    logger.debug(photlist[0].shape[0])


    if (compFile.shape[0] ==1):
        compFile=[[compFile[0][0],compFile[0][1],0.01]]
        compFile=asarray(compFile)
        savetxt(parentPath / "compsUsed.csv", compFile, delimiter=",", fmt='%0.8f')
        sortStars=[[compFile[0][0],compFile[0][1],0.01,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0]]
        sortStars=asarray(sortStars)
        savetxt("stdComps.csv", sortStars, delimiter=",", fmt='%0.8f')
        raise AstrosourceException("Looks like you have a single comparison star!")
    return array(photlist)


def catalogue_call(avgCoord, opt, cat_name, targets, closerejectd):
    data = namedtuple(typename='data',field_names=['ra','dec','mag','emag','cat_name'])

    TABLES = {'APASS':'II/336/apass9',
              'SDSS' :'V/147/sdss12',
              'PanSTARRS' : 'II/349/ps1',
              'SkyMapper' : 'II/358/smss'
              }

    tbname = TABLES.get(cat_name, None)
    kwargs = {'radius':'0.33 deg'}
    kwargs['catalog'] = cat_name

    try:
        v=Vizier(columns=['all']) # Skymapper by default does not report the error columns
        v.ROW_LIMIT=-1
        query = v.query_region(avgCoord, **kwargs)
    except VOSError:
        raise AstrosourceException("Could not find RA {} Dec {} in {}".format(avgCoord.ra.value,avgCoord.dec.value, cat_name))

    if query.keys():
        resp = query[tbname]
    else:
        raise AstrosourceException("Could not find RA {} Dec {} in {}".format(avgCoord.ra.value,avgCoord.dec.value, cat_name))


    logger.debug(f'Looking for sources in {cat_name}')
    if cat_name in ['APASS','PanSTARRS']:
        radecname = {'ra' :'RAJ2000', 'dec': 'DEJ2000'}
    elif cat_name == 'SDSS':
        radecname = {'ra' :'RA_ICRS', 'dec': 'DE_ICRS'}
    elif cat_name == 'SkyMapper':
        radecname = {'ra' :'RAICRS', 'dec': 'DEICRS'}
    else:
        radecname = {'ra' :'raj2000', 'dec': 'dej2000'}

    # Filter out bad data from catalogues
    if cat_name == 'PanSTARRS':
        resp = resp[where((resp['Qual'] == 52) | (resp['Qual'] == 60) | (resp['Qual'] == 61))]
    elif cat_name == 'SDSS':
        resp = resp[resp['Q'] == 3]
    elif cat_name == 'SkyMapper':
        resp = resp[resp['flags'] == 0]

    logger.info("Original high quality sources in calibration catalogue: "+str(len(resp)))

    # Remove any objects close to targets from potential calibrators
    if targets.shape == (4,):
        targets = [targets]
    for tg in targets:
        resp = resp[where(np.abs(resp[radecname['ra']]-tg[0]) > 0.0014) and where(np.abs(resp[radecname['dec']]-tg[1]) > 0.0014)]

    logger.info("Number of calibration sources after removal of sources near targets: "+str(len(resp)))

    # Remove any star from calibration catalogue that has another star in the catalogue within closerejectd arcseconds of it.
    while True:
        fileRaDec = SkyCoord(ra=resp[radecname['ra']].data*degree, dec=resp[radecname['dec']].data*degree)
        idx, d2d, _ = fileRaDec.match_to_catalog_sky(fileRaDec, nthneighbor=2) # Closest matches that isn't itself.
        catReject = []
        for q in range(len(d2d)):
            if d2d[q] < closerejectd*arcsecond:
                catReject.append(q)
        if catReject == []:
            break
        del resp[catReject]
        logger.info(f"Stars rejected that are too close (<5arcsec) in calibration catalogue: {len(catReject)}")

    logger.info(f"Number of calibration sources after removal of sources near other sources: {len(resp)}")


    data.cat_name = cat_name
    data.ra = array(resp[radecname['ra']].data)
    data.dec = array(resp[radecname['dec']].data)

    # extract RA, Dec, Mag and error as arrays
    data.mag = array(resp[opt['filter']].data)
    data.emag = array(resp[opt['error']].data)
    return data

def find_comparisons_calibrated(targets, paths, filterCode, photlist, nopanstarrs=False, nosdss=False, closerejectd=5.0, max_magerr=0.05, stdMultiplier=2, variabilityMultiplier=2):
    sys.stdout.write("⭐️ Find comparison stars in catalogues for calibrated photometry\n")

    FILTERS = {
                'B' : {'APASS' : {'filter' : 'Bmag', 'error' : 'e_Bmag'}},
                'V' : {'APASS' : {'filter' : 'Vmag', 'error' : 'e_Vmag'}},
                'up' : {'SDSS' : {'filter' : 'umag', 'error' : 'e_umag'},
                        'SkyMapper' : {'filter' : 'uPSF', 'error' : 'e_uPSF'},
                        'PanSTARRS': {'filter' : 'umag', 'error' : 'e_umag'}},
                'gp' : {'SDSS' : {'filter' : 'gmag', 'error' : 'e_mag'},
                        'SkyMapper' : {'filter' : 'gPSF', 'error' : 'e_gPSF'},
                        'PanSTARRS': {'filter' : 'gmag', 'error' : 'e_gmag'}},
                'rp' : {'SDSS' : {'filter' : 'rmag', 'error' : 'e_rmag'},
                        'SkyMapper' : {'filter' : 'rPSF', 'error' : 'e_rPSF'},
                        'PanSTARRS': {'filter' : 'rmag', 'error' : 'e_rmag'}},
                'ip' : {'SDSS' : {'filter' : 'imag', 'error' : 'e_imag'},
                        'SkyMapper' : {'filter' : 'iPSF', 'error' : 'e_iPSF'},
                        'PanSTARRS': {'filter' : 'imag', 'error' : 'e_imag'}},
                'zs' : {'SDSS' : {'filter' : 'zmag', 'error' : 'e_zmag'},
                        'SkyMapper' : {'filter' : 'zPSF', 'error' : 'e_zPSF'},
                        'PanSTARRS': {'filter' : 'zmag', 'error' : 'e_zmag'}},
                }


    parentPath = paths['parent']
    calibPath = parentPath / "calibcats"
    if not calibPath.exists():
        os.makedirs(calibPath)

    #Vizier.ROW_LIMIT = -1

    # Get List of Files Used
    fileList=[]
    for line in (parentPath / "usedImages.txt").read_text().strip().split('\n'):
        fileList.append(line.strip())

    logger.debug("Filter Set: " + filterCode)

    # Load compsused
    compFile = genfromtxt(parentPath / 'stdComps.csv', dtype=float, delimiter=',')
    logger.debug(compFile.shape[0])

    if compFile.shape[0] == 13 and compFile.size == 13:
        compFile = [compFile]

    compCoords = SkyCoord(ra=compFile[:,0]*degree, dec=compFile[:,1]*degree)

    # Get Average RA and Dec from file
    logger.debug(average(compFile[:,0]))
    logger.debug(average(compFile[:,1]))
    avgCoord = SkyCoord(ra=(average(compFile[:,0]))*degree, dec=(average(compFile[:,1]))*degree)

    try:
        catalogues = FILTERS[filterCode]
    except IndexError:
        raise AstrosourceException(f"{filterCode} is not accepted at present")

    # Look up in online catalogues

    coords=[]
    for cat_name, opt in catalogues.items():
        try:
            if coords ==[]: #SALERT - Do not search if a suitable catalogue has already been found
                logger.info("Searching " + str(cat_name))
                if cat_name == 'PanSTARRS' and nopanstarrs==True:
                    logger.info("Skipping PanSTARRS")
                elif cat_name == 'SDSS' and nosdss==True:
                    logger.info("Skipping SDSS")
                else:
                    coords = catalogue_call(avgCoord, opt, cat_name, targets=targets, closerejectd=closerejectd)
                    if coords.cat_name == 'PanSTARRS' or coords.cat_name == 'APASS':
                        max_sep=2.5 * arcsecond
                    else:
                        max_sep=1.5 * arcsecond
                    if coords !=[]:
                        cat_used=cat_name


        except AstrosourceException as e:
            logger.debug(e)

    if not coords:
        raise AstrosourceException(f"Could not find coordinate match in any catalogues for {filterCode}")

    #Setup standard catalogue coordinates
    catCoords=SkyCoord(ra=coords.ra*degree, dec=coords.dec*degree)

    #Get calib mags for least variable IDENTIFIED stars.... not the actual stars in compUsed!! Brighter, less variable stars may be too bright for calibration!
    #So the stars that will be used to calibrate the frames to get the OTHER stars.
    calibStands=[]

    lenloop=len(compFile[:,0])

    for q in range(lenloop):
        compCoord=SkyCoord(ra=compFile[q][0]*degree, dec=compFile[q][1]*degree)
        idxcomp,d2dcomp,d3dcomp=compCoord.match_to_catalog_sky(catCoords)
        if d2dcomp < max_sep:
            if not isnan(coords.mag[idxcomp]):
                calibStands.append([compFile[q][0],compFile[q][1],compFile[q][2],coords.mag[idxcomp],coords.emag[idxcomp]])
    logger.info('Calibration Stars Identified below')
    logger.info(calibStands)

    # Get the set of least variable stars to use as a comparison to calibrate the files (to eventually get the *ACTUAL* standards
    #logger.debug(asarray(calibStands).shape[0])
    if asarray(calibStands).shape[0] == 0:
        logger.info("We could not find a suitable match between any of your stars and the calibration catalogue")
        logger.info("You might need to reduce the low value (usually 10000) to get some dimmer stars in script 1")
        logger.info("You might also try using one of --nosdss or --nopanstarrs option (not both!) to prevent comparisons to these catalogues")
        raise AstrosourceException("Stars are too dim to calibrate to.")

    varimin=(min(asarray(calibStands)[:,2])) * variabilityMultiplier

    calibStandsReject=[]
    for q in range(len(asarray(calibStands)[:,0])):
        if calibStands[q][2] > varimin:
            calibStandsReject.append(q)

    calibStands=delete(calibStands, calibStandsReject, axis=0)

    calibStands=asarray(calibStands)

    savetxt(parentPath / "calibStands.csv", calibStands , delimiter=",", fmt='%0.8f')
    # Lets use this set to calibrate each datafile and pull out the calibrated compsused magnitudes

    calibCompUsed=[]

    logger.debug("CALIBRATING EACH FILE")
    for file in fileList:
        logger.debug(file)

        #Get the phot file into memory
        photFile = load(parentPath / file)
        photCoords=SkyCoord(ra=photFile[:,0]*degree, dec=photFile[:,1]*degree)

        #Convert the phot file into instrumental magnitudes
        for r in range(len(photFile[:,0])):
            photFile[r,5]=1.0857 * (photFile[r,5]/photFile[r,4])
            photFile[r,4]=-2.5*log10(photFile[r,4])

        #Pull out the CalibStands out of each file
        tempDiff=[]

        for q in range(len(calibStands[:,0])):
            calibCoord=SkyCoord(ra=calibStands[q][0]*degree,dec=calibStands[q][1]*degree)
            idx,d2d,d3d=calibCoord.match_to_catalog_sky(photCoords)
            tempDiff.append(calibStands[q,3] - photFile[idx,4])

        #logger.debug(tempDiff)
        tempZP= (median(tempDiff))
        #logger.debug(std(tempDiff))


        #Shift the magnitudes in the phot file by the zeropoint
        for r in range(len(photFile[:,0])):
            photFile[r,4]=photFile[r,4]+tempZP


        file = Path(file)
        #Save the calibrated photfiles to the calib directory
        savetxt(calibPath / "{}.calibrated.{}".format(file.stem, file.suffix), photFile, delimiter=",", fmt='%0.8f')



        #Look within photfile for ACTUAL usedcomps.csv and pull them out
        lineCompUsed=[]
        if compUsedFile.shape[0] ==3 and compUsedFile.size == 3:
            lenloop=1
        else:
            lenloop=len(compUsedFile[:,0])
        #logger.debug(compUsedFile.size)
        for r in range(lenloop):
            if compUsedFile.shape[0] ==3 and compUsedFile.size ==3:
                compUsedCoord=SkyCoord(ra=compUsedFile[0]*degree,dec=compUsedFile[1]*degree)
            else:

                compUsedCoord=SkyCoord(ra=compUsedFile[r][0]*degree,dec=compUsedFile[r][1]*degree)
            idx,d2d,d3d=compUsedCoord.match_to_catalog_sky(photCoords)
            lineCompUsed.append(photFile[idx,4])

        #logger.debug(lineCompUsed)
        calibCompUsed.append(lineCompUsed)
        sys.stdout.write('.')
        sys.stdout.flush()



    # Finalise calibcompsusedfile
    #logger.debug(calibCompUsed)

    calibCompUsed=asarray(calibCompUsed)
    #logger.debug(calibCompUsed[0,:])

    finalCompUsedFile=[]
    sumStd=[]
    for r in range(len(calibCompUsed[0,:])):
        #Calculate magnitude and stdev
        sumStd.append(std(calibCompUsed[:,r]))

        if compUsedFile.shape[0] ==3  and compUsedFile.size ==3:
            finalCompUsedFile.append([compUsedFile[0],compUsedFile[1],compUsedFile[2],median(calibCompUsed[:,r]),asarray(calibStands[0])[4]])
        else:
            finalCompUsedFile.append([compUsedFile[r][0],compUsedFile[r][1],compUsedFile[r][2],median(calibCompUsed[:,r]),std(calibCompUsed[:,r])])

    #logger.debug(finalCompUsedFile)
    logger.debug(" ")
    sumStd=asarray(sumStd)

    errCalib = median(sumStd) / pow((len(calibCompUsed[0,:])), 0.5)

    logger.debug("Comparison Catalogue: " + str(cat_used))
    if len(calibCompUsed[0,:]) == 1:
        logger.debug("As you only have one comparison, the uncertainty in the calibration is unclear")
        logger.debug("But we can take the catalogue value, although we should say this is a lower uncertainty")
        logger.debug("Error/Uncertainty in Calibration: " +str(asarray(calibStands[0])[4]))
    else:
        logger.debug("Median Standard Deviation of any one star: " + str(median(sumStd)))
        logger.debug("Standard Error/Uncertainty in Calibration: " +str(errCalib))

    with open(parentPath / "calibrationErrors.txt", "w") as f:
        f.write("Comparison Catalogue: " + str(cat_used)+"\n")
        f.write("Median Standard Deviation of any one star: " + str(median(sumStd)) +"\n")
        f.write("Standard Error/Uncertainty in Calibration: " +str(errCalib))

    #logger.debug(finalCompUsedFile)
    compFile = asarray(finalCompUsedFile)
    savetxt(parentPath / "calibCompsUsed.csv", compFile, delimiter=",", fmt='%0.8f')
    sys.stdout.write('\n')
    return compFile
