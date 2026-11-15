'use client';

import { useMemo, type ComponentProps } from 'react';
import { WidgetProvider } from '@openg2p/registry-widgets';
import { useTranslations } from 'next-intl';
import { useRuntimeConfig } from '@/context/RuntimeConfigContext';
import { dataSourceRequestHandler } from '@/shared/services';
import { brandingToWidgetTheme } from './brandingToWidgetTheme';
// OAN: the only change to upstream's file. Registers the OAN widgets once,
// after the package's defaults, wherever registry widgets render.
import '@/oan/widgets/register';

type RegistryWidgetProviderProps = ComponentProps<typeof WidgetProvider>;

export function RegistryWidgetProvider({
  t,
  theme,
  dataSourceRequestHandler: handler,
  ...props
}: RegistryWidgetProviderProps) {
  const translations = useTranslations();
  const { config } = useRuntimeConfig();
  const brandingTheme = useMemo(
    () => brandingToWidgetTheme(config.branding),
    [config.branding],
  );

  return (
    <WidgetProvider
      {...props}
      t={t ?? translations}
      theme={theme ?? brandingTheme}
      dataSourceRequestHandler={handler ?? dataSourceRequestHandler}
    />
  );
}
