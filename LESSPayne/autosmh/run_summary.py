import numpy as np
import sys, os, time
import yaml
from copy import deepcopy
from scipy.ndimage import gaussian_filter1d

from LESSPayne.smh import Session

def run_summary(cfg):
    name = cfg["output_name"]
    NNpath = cfg["NN_file"]
    outdir = cfg["output_directory"]
    figdir = cfg["figure_directory"]
    if not os.path.exists(outdir): os.makedirs(outdir)
    if not os.path.exists(figdir): os.makedirs(figdir)
    print("Saving to output directory:",outdir)
    print("Saving figures to output directory:",figdir)
    
    smh_fname = os.path.join(outdir, cfg["smh_fname"])
    
    sumcfg = cfg["run_summary"]
    print(sumcfg)
    
    summary_output_dir = sumcfg.get("summary_output_dir", outdir)
    output_suffix = sumcfg.get("output_suffix", outdir)
    linetab_outfname = os.path.join(summary_output_dir, f"{name}_{output_suffix}_lines.txt")
    abundtab_outfname = os.path.join(summary_output_dir, f"{name}_{output_suffix}_abunds.txt")
    if os.path.exists(linetab_outfname): print("Overwriting", linetab_outfname)
    if os.path.exists(abundtab_outfname): print("Overwriting", abundtab_outfname)

    startall = time.time()
    
    session = Session.load(smh_fname)
    if subcfg.get("quick_no_errors",False):
        print("Running quick version (doesn't use line-by-line errors)")
        linetab = get_quick_lines(session)
        summarytab = get_quick_summary(linetab)
        linetab, summarytab = get_quick_limits(session, linetab, summarytab)
    else:
        print("Running full version (needs line-by-line errors)")
        pass

    linetab["star"] = name
    summarytab["star"] = name
    linetab.write(linetab_outfname, format='ascii.fixed_width_two_line', overwrite=True)
    summary.write(abundtab_outfname, format='ascii.fixed_width_two_line', overwrite=True)
    
    print(f"Total time run_summary: {time.time()-startall:.1f}")

def get_quick_lines(session):
    from LESSPayne.smh.spectral_models import ProfileFittingModel, SpectralSynthesisModel
    from LESSPayne.smh.photospheres.abundances import asplund_2009 as solar_composition
    cols = ["index","wavelength","species","expot","loggf",
            "logeps","eqw","e_eqw","fwhm"]
    data = OrderedDict(zip(cols, [[] for col in cols]))
    for i, model in enumerate(session.spectral_models):
        if not model.is_acceptable: continue
        if model.is_upper_limit: continue

        wavelength = model.wavelength
        species = np.ravel(model.species)[0]
        expot = model.expot
        loggf = model.loggf
        if np.isnan(expot) or np.isnan(loggf):
            print(i, species, model.expot, model.loggf)
        try:
            logeps = model.abundances[0]
            fwhm = model.fwhm
        except Exception as e:
            print("ERROR!!!")
            print(i, species, model.wavelength)
            print("Exception:",e)
            logeps, staterr, e_Teff, e_logg, e_vt, e_MH, syserr = np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan

        if isinstance(model, ProfileFittingModel):
            eqw = model.equivalent_width or np.nan
            e_eqw = model.equivalent_width_uncertainty or np.nan
        else:
            eqw = -999
            e_eqw = -999
        input_data = [i, wavelength, species, expot, loggf,
                      logeps, eqw, e_eqw, fwhm]
        for col, x in zip(cols, input_data):
            data[col].append(x)

    tab = astropy.table.Table(data)
    for col in tab.colnames:
        if col in ["index", "wavelength", "species", "loggf", "star"]: continue
        tab[col].format = ".2f"
    return tab

def get_feh(summary_tab):
    try:
        ix1 = np.where(summary_tab["species"]==26.0)[0][0]
    except IndexError:
        print("No feh1: setting to nan")
        feh1 = np.nan
    else:
        feh1 = summary_tab["[X/H]"][ix1]
    try:
        ix2 = np.where(summary_tab["species"]==26.1)[0][0]
    except IndexError:
        print("No feh2: setting to feh1")
        feh2 = feh1
    else:
        feh2 = summary_tab["[X/H]"][ix2]
    return feh1, feh2

def get_quick_summary(tab):
    """
    Take a table of lines and turn them into standard abundance table
    """
    from LESSPayne.smh.spectral_models import ProfileFittingModel, SpectralSynthesisModel
    from LESSPayne.smh.photospheres.abundances import asplund_2009 as solar_composition
    unique_species = np.unique(tab["species"])
    cols = ["species","elem","N",
            "logeps","sigma","stderr",
            "[X/H]"]
    data = OrderedDict(zip(cols, [[] for col in cols]))
    for species in unique_species:
        ttab = tab[tab["species"]==species]
        elem = species_to_element(species)
        N = len(ttab)
        logeps = np.mean(ttab["logeps"])
        stdev = np.std(ttab["logeps"])
        stderr = stdev/np.sqrt(N)


        XH = logeps - solar_composition(species)
        input_data = [species, elem, N,
                      logeps, stdev, stderr,
                      XH
        ]
        assert len(cols) == len(input_data)
        for col, x in zip(cols, input_data):
            data[col].append(x)
    summary_tab = astropy.table.Table(data)
    ## Add in [X/Fe]
    feh1, feh2 = get_feh(summary_tab)

    if len(summary_tab["[X/H]"]) > 0:
        summary_tab["[X/Fe1]"] = summary_tab["[X/H]"] - feh1
        summary_tab["[X/Fe2]"] = summary_tab["[X/H]"] - feh2

        ixion = np.array([x - int(x) > .01 for x in summary_tab["species"]])
        summary_tab["[X/Fe]"] = summary_tab["[X/Fe1]"]
        summary_tab["[X/Fe]"][ixion] = summary_tab["[X/Fe2]"][ixion]
        for col in summary_tab.colnames:
            if col=="N" or col=="species" or col=="elem": continue
            summary_tab[col].format = ".2f"
    else:
        for col in ["[X/Fe]","[X/Fe1]","[X/Fe2]"]:
            summary_tab.add_column(astropy.table.Column(np.zeros(0),col))
    return summary_tab

def get_quick_limits(session, tab, summary_tab):
    from LESSPayne.smh.spectral_models import ProfileFittingModel, SpectralSynthesisModel
    from LESSPayne.smh.photospheres.abundances import asplund_2009 as solar_composition
    ## Add in upper limits to line data
    cols = ["index","wavelength","species","expot","loggf",
            "logeps","eqw","e_eqw","fwhm"]
    feh1, feh2 = get_feh(summary_tab)

    assert len(cols)==len(tab.colnames)
    data = OrderedDict(zip(cols, [[] for col in cols]))
    for i, model in enumerate(session.spectral_models):
        if not model.is_upper_limit: continue
        if not model.is_acceptable: continue

        wavelength = model.wavelength
        species = np.ravel(model.species)[0]
        expot = model.expot or np.nan
        loggf = model.loggf or np.nan
        try:
            logeps = model.abundances[0]
            fwhm = model.fwhm
        except:
            logeps = np.nan
            fwhm = np.nan

        input_data = [i, wavelength, species, expot, loggf,
                      logeps, np.nan, np.nan, fwhm]
        for col, x in zip(cols, input_data):
            data[col].append(x)
    tab_ul = astropy.table.Table(data)
    tab_ul["logeps"].format = ".2f"
    tab_ul["fwhm"].format = ".2f"
    tab = astropy.table.vstack([tab, tab_ul])

    ## Add in upper limits to summary table
    ul_species = np.unique(tab_ul["species"])
    cols = ["species","elem","N",
            "logeps","sigma","stderr",
            "[X/H]"] + ["[X/Fe1]","[X/Fe2]","[X/Fe]"]
    assert len(cols)==len(summary_tab.colnames)
    data = OrderedDict(zip(cols, [[] for col in cols]))
    for species in ul_species:
        if species in summary_tab["species"]: continue
        ttab_ul = tab_ul[tab_ul["species"]==species]
        elem = species_to_element(species)
        N = len(ttab_ul)
        limit_logeps = np.min(ttab_ul["logeps"])
        limit_XH = limit_logeps - solar_composition(species)
        limit_XFe1 = limit_XH - feh1
        limit_XFe2 = limit_XH - feh2
        limit_XFe = limit_XFe2 if (species - int(species) > .01) else limit_XFe1
        input_data = [species, elem, N,
                      limit_logeps, np.nan, np.nan,
                      limit_XH, limit_XFe1, limit_XFe2, limit_XFe
        ]
        for col, x in zip(cols, input_data):
            data[col].append(x)
    summary_tab_ul = astropy.table.Table(data)
    if len(summary_tab_ul) > 0:
        if len(summary_tab) > 0:
            summary_tab = astropy.table.vstack([summary_tab, summary_tab_ul])
        else:
            summary_tab = summary_tab_ul

    return tab, summary_tab


def get_fullerrors_lines(session, minerr=0.001, default_esys=0.1, estimate_systematic_error=False):
    """
    Pull out all of the lines from the SMH file, including the stellar parameter uncertainties
    """
    from LESSPayne.smh.spectral_models import ProfileFittingModel, SpectralSynthesisModel
    cols = ["index","wavelength","species","expot","loggf",
            "logeps","e_stat","eqw","e_eqw","fwhm",
            "e_Teff","e_logg","e_vt","e_MH","e_sys",
            "e_tot","weight"]
    data = OrderedDict(zip(cols, [[] for col in cols]))
    for i, model in enumerate(session.spectral_models):
        if not model.is_acceptable: continue
        if model.is_upper_limit: continue
        
        wavelength = model.wavelength
        species = np.ravel(model.species)[0]
        expot = model.expot
        loggf = model.loggf
        if np.isnan(expot) or np.isnan(loggf):
            print(i, species, model.expot, model.loggf)
        try:
            logeps = model.abundances[0]
            staterr = model.metadata["1_sigma_abundance_error"]
            if isinstance(model, SpectralSynthesisModel):
                (named_p_opt, cov, meta) = model.metadata["fitted_result"]
                if np.isfinite(cov[0,0]**0.5):
                    staterr = max(staterr, cov[0,0]**0.5)
                assert ~np.isnan(staterr)
            # apply minimum
            staterr = np.sqrt(staterr**2 + minerr**2)
            sperrdict = model.metadata["systematic_stellar_parameter_abundance_error"]
            e_Teff = sperrdict["effective_temperature"]
            e_logg = sperrdict["surface_gravity"]
            e_vt = sperrdict["microturbulence"]
            e_MH = sperrdict["metallicity"]
            e_all = np.array([e_Teff, e_logg, e_vt, e_MH])
            syserr_sq = e_all.T.dot(rhomat.dot(e_all))
            syserr = np.sqrt(syserr_sq)
            fwhm = model.fwhm
        except Exception as e:
            print("ERROR!!!")
            print(i, species, model.wavelength)
            print("Exception:",e)
            logeps, staterr, e_Teff, e_logg, e_vt, e_MH, syserr = np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan

        if isinstance(model, ProfileFittingModel):
            eqw = model.equivalent_width or np.nan
            e_eqw = model.equivalent_width_uncertainty or np.nan
        else:
            eqw = -999
            e_eqw = -999
        #toterr = np.sqrt(staterr**2 + syserr**2)
        input_data = [i, wavelength, species, expot, loggf,
                      logeps, staterr, eqw, e_eqw, fwhm,
                      e_Teff, e_logg, e_vt, e_MH, syserr,
                      np.nan, np.nan]
        for col, x in zip(cols, input_data):
            data[col].append(x)
    tab = astropy.table.Table(data)
    
    tab["e_sys"] = default_esys
    if estimate_systematic_error:
        for species in np.unique(tab["species"]):
            ix = np.where(tab["species"]==species)[0]
            t = tab[ix]
    
            # Estimate systematic error s
            s = s_old = 0.
            #s_max = 2.
            s_max = 3. # Updated to a larger value because it was not always converging.
            #delta = struct2array(t["e_Teff","e_logg","e_vt","e_MH"].as_array())
            ex = t["e_stat"]
            for i in range(100):
                #sigma_tilde = np.diag(s**2 + ex**2) + (delta.dot(rhomat.dot(delta.T)))
                #sigma_tilde_inv = np.linalg.inv(sigma_tilde)
                #w = np.sum(sigma_tilde_inv, axis=1)
                w = np.ones(len(t))
    
                xhat = np.sum(w*t["logeps"])/np.sum(w)
                dx = t["logeps"] - xhat
                def func(s):
                    return np.sum(dx**2 / (ex**2 + s**2)**2) - np.sum(1/(ex**2 + s**2))
                if func(0) < func(s_max):
                    s = 0
                    break
                try:
                    s = optimize.brentq(func, 0, s_max, xtol=.001)
                except ValueError as e:
                    print("ERROR FOR SPECIES",species)
                    print(e)
                    print("s_max:",s_max)
                    print("func(0)",func(0))
                    print("func(s_max)",func(s_max))
                    print("Figure out what you should do to s_max here:")
                    import pdb; pdb.set_trace()
                    raise
    
                if np.abs(s_old - s) < 0.01:
                    break
                s_old = s
            else:
                print(species,"s did not converge!")
            print("Final in {} iter: {:.1f} {:.3f}".format(i+1, species, s))
            tab["e_sys"][ix] = s
    
            ## Stuff below here is a relic of Ji+2020b (S5 paper)
            ## We will figure this out someday, but that day is not today
            #tab["e_tot"][ix] = np.sqrt(s**2 + ex**2)
            #sigma_tilde = np.diag(tab["e_tot"][ix]**2) + (delta.dot(rhomat.dot(delta.T)))
            #sigma_tilde_inv = np.linalg.inv(sigma_tilde)
            #w = np.sum(sigma_tilde_inv, axis=1)
            #wb = np.sum(sigma_tilde_inv, axis=0)
            #assert np.allclose(w,wb,rtol=1e-6), "Problem in species {:.1f}, Nline={}, e_sys={:.2f}".format(species, len(t), s)
            #tab["weight"][ix] = w
    
    etot2 = np.zeros(len(tab))
    for col in ["e_stat", "e_sys", "e_Teff", "e_logg", "e_vt", "e_MH"]:
        etot2 = etot2 + tab[col]**2
    tab["e_tot"] = np.sqrt(etot2)
    tab["weight"] = tab["e_tot"]**-2    

    for col in tab.colnames:
        if col in ["index", "wavelength", "species", "loggf", "star"]: continue
        tab[col].format = ".3f"
    return tab

def get_fullerrors_summary(tab):
    """
    Take a table of lines and turn them into standard abundance table
    """
    from LESSPayne.smh.spectral_models import ProfileFittingModel, SpectralSynthesisModel
    
    return None