import React from 'react';
import ReactDOM from 'react-dom/client';
import { App as AntApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import App from './App';
import './styles.css';

dayjs.locale('zh-cn');
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={{
      token: { colorPrimary: '#315b88', colorSuccess: '#2f8068', colorWarning: '#b58232', colorInfo: '#315b88',
        colorText: '#202f41', colorTextSecondary: '#677587', colorBorder: '#dce2e9', colorBgLayout: '#f4f6f8',
        borderRadius: 7, fontSize: 14, fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
        controlHeight: 38 },
      components: { Table: { headerBg: '#f8f9fb', rowHoverBg: '#f6f9fc', cellPaddingBlock: 15 },
        Button: { primaryShadow: 'none' }, Menu: { darkItemBg: '#14273e', darkSubMenuItemBg: '#14273e', darkItemSelectedBg: '#29425e' } },
    }}>
      <AntApp><App /></AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
