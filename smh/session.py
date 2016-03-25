#!/usr/bin/env python
# -*- coding: utf-8 -*-

""" An object to manage SMH sessions. """

from __future__ import (division, print_function, absolute_import,
                        unicode_literals)

__all__ = ["Session"]

import os
import yaml
from six import string_types

from . import specutils


class BaseSession(object):
    """
    An abstract class for a SMH session.
    """
    pass

 


class Session(BaseSession):
    """
    An object to manage a session in SMH.
    """

    # The default settings path is only defined (hard-coded) here.
    _default_settings_path = os.path.expanduser("~/.smh_session.defaults")

    def __init__(self, spectrum_paths, **kwargs):
        """
        Create a new session from input spectra.

        :param spectrum_paths:
            Filename of a single spectrum, or an iterable of spectrum filenames.
        """

        if isinstance(spectrum_paths, string_types):
            spectrum_paths = (spectrum_paths, )

        # Load the spectra and flatten all orders into a single list.
        input_spectra = \
            sum(list(map(specutils.Spectrum1D.read, spectrum_paths)), [])

        # Sort orders from blue to red.
        input_spectra.sort(key=lambda order: order.dispersion.mean())

        # TODO: Store the path names internally for provenance?

        # Extract basic metadata information from the spectrum headers if
        # possible: RA, DEC, OBJECT
        # TODO: Include UTDATE, etc to calculate helio/bary-centric corrections.
        common_metadata = {}
        common_metadata_keys = ["RA", "DEC", "OBJECT"] \
            + kwargs.pop("common_metadata_keys", [])

        for key in common_metadata_keys:
            for order in input_spectra:
                if key in order.metadata:
                    common_metadata[key] = order.metadata[key]
                    break

        self.input_spectra = input_spectra
        self.input_spectra_paths = spectrum_paths

        return None


    def _default(self, input_value, default_key_tree):
        """
        Return the input value if it is valid (i.e., not `None`), or return the
        default session value.

        :param input_value:
            The value provided by the user.

        :param default_key_tree:
            A tuple containing a tree of dictionary keys.
        """

        if input_value is not None:
            return input_value

        with open(self._default_settings_path, "rb") as fp:
            default = yaml.load(fp)

        for key in default_key_tree:
            try:
                default = default[key]
            except KeyError:
                raise KeyError("no default session value found for {0}".format(
                    default_key_tree))
                
        return default



    @classmethod
    def from_filename(cls, session_path, **kwargs):
        """
        Create a Session from a path saved to disk.
        """

        raise NotImplementedError


    def rv_measure(self, template_spectrum=None, wavelength_region=None,
        resample=None, apodize=None, normalization_kwargs=None):
        """
        Measure the observed radial velocity by cross-correlating an individual
        echelle order with a normalized rest-frame template spectrum. The most
        suitable order is determined by the `wavelength_region` given.

        :param template_spectrum: [optional]
            The rest-frame template spectrum to cross-correlate against. This
            should be a `specutils.Spectrum1D` object or a `str`-type pointing
            to a spectrum path.

        :param wavelength_region: [optional]
            The preferred wavelength region(s) to use for cross-correlation. The
            most suitable input spectrum will be determined from this supplied
            range.

        :param resample: [optional]
            Re-sample to the 'template' or 'observed' spectrum.

        :param apodize: [optional]
            What fraction of the pixels to apodize (on both ends) before
            performing the cross-correlation.

        :param normalization_kwargs: [optional]
            Keyword arguments that are passed directly to the 
            `Spectrum1D.fit_continuum` function.

        Note
        ----
        If these parameters are not specified, then defaults are read from the
        session defaults file.
        """

        # Read in everything from defaults as necessary.
        template_spectrum = \
            self._default(template_spectrum, ("rv", "template_spectrum"))
        wavelength_region = \
            self._default(wavelength_region, ("rv", "wavelength_regions"))
        resample = self._default(resample, ("rv", "resample"))
        apodize = self._default(apodize, ("rv", "apodize"))
        normalization_kwargs = \
            self._default(normalization_kwargs, ("rv", "normalization"))

        # Is the template spectrum actually a filename?
        if isinstance(template_spectrum, string_types):
            template_spectrum = specutils.Spectrum1D.read(template_spectrum,
                debug=True)

        # Check to see if wavelength region is a list of entries.
        try:
            int(wavelength_region[0])
        except (TypeError, ValueError):
            # It is (probably) a list of 2-length tuples.
            None
        else:
            wavelength_region = [wavelength_region]

        # Find the order best suitable for the preferred wavelength region.
        for wl_start, wl_end in wavelength_region:
            # Does the template cover this range?
            if  not (wl_start > template_spectrum.dispersion[0] \
                and  wl_end   < template_spectrum.dispersion[-1]):
                continue

            # Do any observed orders cover any part of this range?
            overlaps, indices = specutils.find_overlaps(
                self.input_spectra, (wl_start, wl_end), return_indices=True)
            if not overlaps:
                continue

            # The first spectral index has the most overlap with the range.
            overlap_index = indices[0]
            overlap_order = overlaps[0]
            break

        else:
            raise ValueError("no wavelength regions are common to the template "
                             "and the observed spectra")

        # Normalize that order using the normalization settings supplied.
        observed_spectrum = overlap_order.fit_continuum(**normalization_kwargs)

        # Perform cross-correlation with the template spectrum.
        rv, rv_uncertainty, ccf = specutils.cross_correlate(
            observed_spectrum, template_spectrum, (wl_start, wl_end), 
            apodize=apodize, resample=resample)

        # Store the measured information as part of the session.
        # TODO: Should we store these as a NamedTuple instead?
        self.rv = {
            # Measurements
            "rv_measured": rv,
            "rv_uncertainty": rv_uncertainty,
            "order_index": overlap_index,
            "normalized_order": observed_spectrum,
            "ccf": ccf,
            "heliocentric_correction": np.nan, # TODO
            "barycentric_correction": np.nan, #TODO

            # Input settings
            "template_spectrum": template_spectrum,
            "wavelength_region": [wl_start, wl_end],
            "resample": resample,
            "apodize": apodize,
            "normalization": normalization_kwargs.copy()
        }

        return (rv, rv_uncertainty)


    def rv_apply(self, rv):
        """
        Apply a radial velocity correction to the input spectra.
        
        :param rv:
            The radial velocity correction (in km/s) to apply.
        """

        self.rv["rv_applied"] = rv
        return None

