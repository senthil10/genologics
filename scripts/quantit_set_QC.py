#!/usr/bin/env python
DESC = """EPP script for Quant-iT mesurements to verify standards, calculate
concentrations and load input artifact-udfs and output file-udfs of the process 
with concentation values and fluorescence intensity

Reads from:
    --Lims fields--
    "Saturation threshold of fluorescence intensity"    process udf 
    "Allowed %CV of duplicates"                         process udf
    "Fluorescence intensity 1"  udf of input analytes to the process
    "Fluorescence intensity 2"  udf of input analytes to the process

    --files--
    "Standards File (.txt)"     "shared result file" uploaded by user.   
    "Quant-iT Result File 1"    "shared result file" uploaded by user.
    "Quant-iT Result File 2"    "shared result file" uploaded by user. (optional)

Writes to:
    --Lims fields--
    "Intensity check"           udf of process artifacts (result file)
    "%CV"                       udf of process artifacts (result file)
    "QC"                        qc-flag of process artifacts (result file)

Logging:
The script outputs a regular log file with regular execution information.

1) compares the udfs "Fluorescence intensity 1" and "Fluorescence intensity 2" 
with the Saturation threshold of fluorescence intensity. If either of these two 
udfs >= Saturation threshold of fluorescence intensity, assign "Saturated" to 
the udf "Intensity check" and assign "Fail" to the sample. Otherwise assign 
"OK" to the analyte "Intensity check".

2) For a sample with duplicate measurements, "%CV" is calculated by the formula: 
%CV= (SD of "Fluorescence intensity 1" and "Fluorescence intensity 2")/(Mean of 
"Fluorescence intensity 1" and ""Fluorescence intensity 2). 
Copy the values to the sample analyte "%CV".

3) If "%CV" >= Allowed %CV of duplicates, assign "Fail" to the sample. 

4) For a sample with only one measurement, if it passes in step 2, a "Pass" should 
be assigned to the QC flag. For a sample with duplicate measurements, if it passes 
both step 2 and step 4, a "Pass" should be assigned to the QC flag.

Written by Maya Brandi 
"""

import os
import sys
import logging
import numpy as np

from argparse import ArgumentParser
from requests import HTTPError
from genologics.lims import Lims
from genologics.config import BASEURI,USERNAME,PASSWORD
from genologics.entities import Process
from genologics.epp import EppLogger
from genologics.epp import set_field
from genologics.epp import ReadResultFiles
lims = Lims(BASEURI,USERNAME,PASSWORD)

class QunatiTQC():
    def __init__(self, process):
        self.result_files = process.result_files()
        self.udfs = dict(process.udf.items())
        self.requiered_udfs = set(["Allowed %CV of duplicates",
            "Saturation threshold of fluorescence intensity",
            "Minimum required concentration (ng/ul)"])
        self.abstract = []
        self.missing_udfs = []
        self.hig_CV_fract = 0
        self.saturated = 0
        self.low_conc = 0
        self.flour_int_missing = 0
        self.no_failed = 0

    def saturation_QC(self, result_file, udfs):
        treshold = self.udfs["Saturation threshold of fluorescence intensity"]
        allowed_dupl = self.udfs["Allowed %CV of duplicates"]
        fint_2 = udfs["Fluorescence intensity 2"] if udfs.has_key("Fluorescence intensity 2") else None
        fint_1 = udfs["Fluorescence intensity 1"] if udfs.has_key("Fluorescence intensity 1") else None
        if fint_1 or fint_2:
            qc_flag = "PASSED"
            if (fint_1 >= treshold) or (fint_2 >= treshold):
                result_file.udf["Intensity check"] = "Saturated"
                qc_flag = "FAILED"
                self.saturated +=1
            else:
                result_file.udf["Intensity check"] = "OK"
                if fint_1 and fint_2:
                    std = np.std([fint_1, fint_2])
                    mean = np.mean([fint_1, fint_2])
                    procent_CV = np.true_divide(std,mean)
                    result_file.udf["%CV"] = procent_CV
                    if procent_CV >= allowed_dupl:
                        qc_flag = "FAILED"
                        self.hig_CV_fract +=1
            return qc_flag
        else:
            self.flour_int_missing +=1
            return None

    def concentration_QC(self, result_file, result_file_udfs):
        min_conc = self.udfs["Minimum required concentration (ng/ul)"]
        if result_file_udfs['Concentration'] < min_conc:
            return "FAILED"
            self.low_conc +=1
        else:
            return "PASSED"

    def assign_QC_flag(self):
        if self.requiered_udfs.issubset(self.udfs.keys()):
            for result_file in self.result_files:
                result_file_udfs = dict(result_file.udf.items())
                QC = self.concentration_QC(result_file, result_file_udfs)
                QC = self.saturation_QC(result_file, result_file_udfs)
                self.no_failed +=1 if QC == "FAILED" else 0
                if QC:
                    result_file.qc_flagg = QC
                    set_field(result_file)
        else:
            self.missing_udfs = ', '.join(list(self.requiered_udfs))

def main(lims, pid, epp_logger):
    process = Process(lims,id = pid)
    QiT = QunatiTQC(process)
    QiT.assign_QC_flag()
    if QiT.flour_int_missing:
        QiT.abstract.append("Fluorescence intensity is missing for {0} samples.".format(QiT.flour_int_missing))
    if QiT.missing_udfs:

        QiT.abstract.append("Some of the folowing requiered udfs seems to be missing: {0}. Could not set QC flaggs.".format(QiT.missing_udfs))
    else:
        QiT.abstract.append("{0} out of {1} samples failed QC. ".format(QiT.no_failed, len(process.result_files())))
    if QiT.saturated:
        QiT.abstract.append("{0} samples had saturated fluorescence intensity.".format(QiT.saturated))
    if QiT.hig_CV_fract:
        QiT.abstract.append("{0} samples had high %CV.".format(QiT.hig_CV_fract))
    if QiT.low_conc:
        QiT.abstract.append("{0} samples had high low concentration.".format(QiT.low_conc))

    QiT.abstract = list(set(QiT.abstract))
    print >> sys.stderr, ' '.join(QiT.abstract)

if __name__ == "__main__":
    parser = ArgumentParser(description=DESC)
    parser.add_argument('--pid', default = None , dest = 'pid',
                        help='Lims id for current Process')
    parser.add_argument('--log', dest = 'log',
                        help=('File name for standard log file, '
                              'for runtime information and problems.'))

    args = parser.parse_args()
    lims = Lims(BASEURI,USERNAME,PASSWORD)
    lims.check_version()

    with EppLogger(log_file=args.log, lims=lims, prepend=True) as epp_logger:
        main(lims, args.pid, epp_logger)

