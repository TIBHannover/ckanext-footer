"""
Provides up to 10 autocomplete suggestions based on the user's input.
"""

def molecule_autocomplete_search(context, data_dict):
    model = context['model']
    session = context['session']
    term = data_dict.get('term', '').strip()

    query = session.query(model.Molecule).filter(
        (model.Molecule.inchi_key.ilike(f"%{term}%")) |
        (model.Molecule.iupac_name.ilike(f"%{term}%"))
    ).limit(10)

    molecules = query.all()

    serialized = []
    for molecule in molecules:
        serialized.append({
            'id': molecule.id,
            'inchi_key': molecule.inchi_key,
            'iupac_name': molecule.iupac_name
        })

    return {'results': serialized}
