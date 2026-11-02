// ESLint 9 flat config (T-4379). Next 16 removed `next lint`; this is the
// same rule set `.eslintrc.json` named, `next/core-web-vitals`.
import nextVitals from 'eslint-config-next/core-web-vitals';

const config = [
  ...nextVitals,
  {
    // New in eslint-plugin-react-hooks 7, which Next 16 brings: rules written
    // for the React Compiler. They flag 48 places in code that ESLint 8 passed
    // (31 setState calls inside effects, 16 ref reads during render, 1
    // mutation). Off so this upgrade changes no behaviour; adopting them is
    // T-4393, one component at a time.
    rules: {
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/refs': 'off',
      'react-hooks/immutability': 'off',
    },
  },
  { ignores: ['.next/**', '.next-*/**', 'node_modules/**', 'next-env.d.ts', 'public/**'] },
];

export default config;
