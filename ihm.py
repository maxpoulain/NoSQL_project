import tkinter as tk
from tkinter import *
import folium
import pandas as pd
import geopandas as gpd
import os
import json
from cassandra.cluster import Cluster

root = tk.Tk()

def update_btn_text():
    city = str(entree.get())
    code = int(str(liste.get(ACTIVE)))
    print(city)

    # request
    cluster = Cluster(['ec2-35-170-17-129.compute-1.amazonaws.com'])
    session = cluster.connect('gdelt')

    #session.execute("""SELECT (day, country, frequency) FROM mentions_by_location_eventcode WHERE location = %(city)s AND eventcode = %(code)s""",{'city': city, 'code': code})



    query = "SELECT day, country, frequency FROM mentions_by_location_eventcode WHERE location = %s AND eventcode = %s"
    mentions = pd.DataFrame(list(session.execute(query, [city, code])))
    mentions['day'] = mentions['day'].apply(lambda x: x[:-1])
    mentions = mentions.groupby(['day', 'country'], as_index=False).sum()
    mentions['day'] = pd.to_datetime(mentions['day'])
    mentions['day'] = mentions['day'].apply(lambda x: x.strftime('%s'))
    mentions_by_day = mentions.pivot(index='day', columns='country', values='frequency')
    mentions_by_day.fillna(0.0, inplace=True)
    medias_by_country = pd.read_csv('domainCountry.csv').groupby(by='FIPSCountryCode').size()
    ratios = medias_by_country[mentions_by_day.columns]
    mentions_by_day = mentions_by_day.apply(lambda row: row/ratios, axis=1)
    max_mentions = mentions_by_day.max()
    mentions_by_day = mentions_by_day/max_mentions
    fips_to_iso3 = pd.read_csv('iso3_fips.csv', sep=';', index_col='fips')
    def convert_countrycode(fips):
        iso3 = fips_to_iso3.loc[fips]['iso3']
        return iso3

    mentions_by_day.rename(convert_countrycode, axis='columns', inplace=True)
    assert 'naturalearth_lowres' in gpd.datasets.available
    datapath = gpd.datasets.get_path('naturalearth_lowres')
    gdf = gpd.read_file(datapath)
    gdf = gdf.set_index('iso_a3')

    gdelt = mentions_by_day.applymap(lambda cell: {'color': '#ff0000', 'opacity':cell})

    styledict = gdelt.to_dict()

    from branca.element import Figure, JavascriptLink
    from folium.features import GeoJson
    from jinja2 import Template

    class TimeSliderChoropleth(GeoJson):
        """
        Creates a TimeSliderChoropleth plugin to append into a map with Map.add_child.
        Parameters
        ----------
        data: str
            geojson string
        styledict: dict
            A dictionary where the keys are the geojson feature ids and the values are
            dicts of `{time: style_options_dict}`
        """
        def __init__(self, data, styledict, name=None, overlay=True, control=True, **kwargs):
            super(TimeSliderChoropleth, self).__init__(data, name=name, overlay=overlay, control=control)
            if not isinstance(styledict, dict):
                raise ValueError('styledict must be a dictionary, got {!r}'.format(styledict))
            for val in styledict.values():
                if not isinstance(val, dict):
                    raise ValueError('Each item in styledict must be a dictionary, got {!r}'.format(val))

            # Make set of timestamps.
            timestamps = set()
            for feature in styledict.values():
                timestamps.update(set(feature.keys()))
            timestamps = sorted(list(timestamps))

            self.timestamps = json.dumps(timestamps)
            self.styledict = json.dumps(styledict, sort_keys=True, indent=2)

            self._template = Template(u"""
                {% macro script(this, kwargs) %}
                    var timestamps = {{ this.timestamps }};
                    var styledict = {{ this.styledict }};
                    var current_timestamp = timestamps[0];
                    // insert time slider
                    d3.select("body").insert("p", ":first-child").append("input")
                        .attr("type", "range")
                        .attr("width", "100px")
                        .attr("min", 0)
                        .attr("max", timestamps.length - 1)
                        .attr("value", 0)
                        .attr("id", "slider")
                        .attr("step", "1")
                        .style('align', 'center');
                    // insert time slider output BEFORE time slider (text on top of slider)
                    d3.select("body").insert("p", ":first-child").append("output")
                        .attr("width", "100")
                        .attr("id", "slider-value")
                        .style('font-size', '18px')
                        .style('text-align', 'center')
                        .style('font-weight', '500%');
                    var datestring = new Date(parseInt(current_timestamp)*1000).toDateString();
                    d3.select("output#slider-value").text(datestring);
                    fill_map = function(){
                        for (var feature_id in styledict){
                            let style = styledict[feature_id]//[current_timestamp];
                            var fillColor = 'white';
                            var opacity = 0;
                            if (current_timestamp in style){
                                fillColor = style[current_timestamp]['color'];
                                opacity = style[current_timestamp]['opacity'];
                                d3.selectAll('#feature-'+feature_id
                                ).attr('fill', fillColor)
                                .style('fill-opacity', opacity);
                            }
                        }
                    }
                    d3.select("#slider").on("input", function() {
                        current_timestamp = timestamps[this.value];
                    var datestring = new Date(parseInt(current_timestamp)*1000).toDateString();
                    d3.select("output#slider-value").text(datestring);
                    fill_map();
                    });
                    {% if this.highlight %}
                        {{this.get_name()}}_onEachFeature = function onEachFeature(feature, layer) {
                            layer.on({
                                mouseout: function(e) {
                                if (current_timestamp in styledict[e.target.feature.id]){
                                    var opacity = styledict[e.target.feature.id][current_timestamp]['opacity'];
                                    d3.selectAll('#feature-'+e.target.feature.id).style('fill-opacity', opacity);
                                }
                            },
                                mouseover: function(e) {
                                if (current_timestamp in styledict[e.target.feature.id]){
                                    d3.selectAll('#feature-'+e.target.feature.id).style('fill-opacity', 1);
                                }
                            },
                                click: function(e) {
                                    {{this._parent.get_name()}}.fitBounds(e.target.getBounds());
                            }
                            });
                        };
                    {% endif %}
                    var {{this.get_name()}} = L.geoJson(
                        {% if this.embed %}{{this.style_data()}}{% else %}"{{this.data}}"{% endif %}
                        {% if this.smooth_factor is not none or this.highlight %}
                            , {
                            {% if this.smooth_factor is not none  %}
                                smoothFactor:{{this.smooth_factor}}
                            {% endif %}
                            {% if this.highlight %}
                                {% if this.smooth_factor is not none  %}
                                ,
                                {% endif %}
                                onEachFeature: {{this.get_name()}}_onEachFeature
                            {% endif %}
                            }
                        {% endif %}
                        ).addTo({{this._parent.get_name()}}
                    );
                {{this.get_name()}}.setStyle(function(feature) {feature.properties.style;});
                    {{ this.get_name() }}.eachLayer(function (layer) {
                        layer._path.id = 'feature-' + layer.feature.id;
                        });
                    d3.selectAll('path')
                    .attr('stroke', 'white')
                    .attr('stroke-width', 0.8)
                    .attr('stroke-dasharray', '5,5')
                    .attr('fill-opacity', 0);
                    fill_map();
                {% endmacro %}
                """)

        def render(self, **kwargs):
            super(TimeSliderChoropleth, self).render(**kwargs)
            figure = self.get_root()
            assert isinstance(figure, Figure), ('You cannot render this Element '
                                                'if it is not in a Figure.')
            figure.header.add_child(JavascriptLink('https://d3js.org/d3.v4.min.js'), name='d3v4')

    m = folium.Map([0, 0], zoom_start=2)

    g = TimeSliderChoropleth(
        gdf.to_json(),
        styledict=styledict,

    ).add_to(m)

    m.save(os.path.join('gdelt_viz.html'))
    import webbrowser
    webbrowser.open('file://' + os.path.realpath('gdelt_viz.html'))



# First line
p_horiz = PanedWindow(root, orient=HORIZONTAL)
p_horiz.pack(side=TOP)
p_horiz.add(Label(p_horiz, text='City : ', background='white', anchor=CENTER))
entree = Entry(p_horiz, textvariable="string", width=30, background='lightgrey')
p_horiz.add(entree)

# Second line

p_horiz2 =  PanedWindow(root, orient=HORIZONTAL)

p_horiz2.add(Label(p_horiz2, text='Event Code: ', background='white', anchor=CENTER))
liste = Listbox(p_horiz2)
liste.insert(1, "180")
liste.insert(2, "183")
p_horiz2.add(liste)

p_horiz.pack()
p_horiz2.pack()

btn_text = tk.StringVar()
btn = tk.Button(root, textvariable=btn_text, command=update_btn_text)
btn_text.set("Launch request")

btn.pack()



root.mainloop()
