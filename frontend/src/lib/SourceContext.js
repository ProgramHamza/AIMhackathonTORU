import { createContext, useContext } from 'react';
import { makeDocumentStore } from './sources';

export const SourceContext = createContext({
  store: makeDocumentStore([]),
  openSource: () => {},
  activeKey: null,
  activeContradiction: null,
  openRecord: () => {},
  recordOpen: false,
  focusContradiction: () => {},
});

export const useSources = () => useContext(SourceContext);
