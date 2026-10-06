import React from 'react';
import ReactDOM from 'react-dom/client';
import '@fontsource/poppins/400.css';
import '@fontsource/poppins/500.css';
import '@fontsource/poppins/600.css';
import '@fontsource/poppins/700.css';
import 'leaflet/dist/leaflet.css';
import './styles.css';
import { LanguageProvider } from './i18n/LanguageContext';
import HomePage from './pages/HomePage';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <LanguageProvider>
      <HomePage />
    </LanguageProvider>
  </React.StrictMode>,
);
