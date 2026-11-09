// Mapové podklady: dnešní OpenStreetMap a II. vojenské mapování 1836–1852 (VÚGTK a HÚ AV ČR, chartae-antiquae.cz).
import type * as Leaflet from 'leaflet';

export function podklady(L: typeof Leaflet, map: Leaflet.Map, { stara = false, sbalene = false } = {}) {
  const dnes = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  });
  const vojenske = L.tileLayer('https://www.chartae-antiquae.cz/TMS/Military2/{z}/{x}/{y}', {
    maxZoom: 18,
    maxNativeZoom: 17,
    attribution: 'II. vojenské mapování 1836–1852 &copy; <a href="https://chartae-antiquae.cz/cs/maps/2military">VÚGTK &amp; HÚ AV ČR</a>',
  });
  (stara ? vojenske : dnes).addTo(map);
  L.control.layers({ 'Dnešní mapa': dnes, 'Mapa 1836–1852': vojenske }, {}, { collapsed: sbalene || window.innerWidth <= 700, position: 'topright' }).addTo(map);
}
